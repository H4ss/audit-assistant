"""Application web locale (FastAPI + Jinja2, sans CDN ni compilation).

Sécurité de l'interface locale :
  * écoute sur la boucle locale uniquement (vérifié au lancement) ;
  * en-tête Host restreint à la boucle locale (protection contre le DNS rebinding) ;
  * toute écriture exige le jeton d'interface (autorité humaine), distinct du
    jeton de l'agent, et une origine locale (protection CSRF).
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from paladin import __version__, store
from paladin.agent import jobs as agent_jobs
from paladin.analysis import safe_repo_file
from paladin.config import Settings
from paladin.contracts import (
    DISCUSSION_COMMENT,
    EXCEL_NOT_AN_ISSUE,
    EXCEL_TRUE_POSITIVE,
    DecisionAction,
    Verdict,
)
from paladin.db import open_database
from paladin.review import decisions as dec
from paladin.review import queue as q
from paladin.store import ConflictError
from paladin.util import loads, utcnow

_HERE = Path(__file__).parent
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
AUTHOR = "analyste"

VERDICT_LABELS = {
    "TRUE_POSITIVE": EXCEL_TRUE_POSITIVE,
    "NOT_AN_ISSUE": EXCEL_NOT_AN_ISSUE,
    "NEEDS_REVIEW": "À investiguer / indéterminé",
}
EXPORT_LABELS = {
    "not_exported": "Excel : à exporter",
    "exported": "Excel : à jour",
    "stale": "Excel : PÉRIMÉ — réexporter",
    "conflict": "Excel : conflit",
}
REVIEW_LABELS = {
    "to_review": "À revoir",
    "investigating": "À investiguer",
    "validated": "Validé",
    "reexam_required": "Réexamen requis",
}


def _flash(conn, campaign_id: str, message: str, level: str = "info", details: Any = None) -> None:
    store.set_ui_state(conn, campaign_id, "flash", {"message": message, "level": level, "details": details})


def _pop_flash(conn, campaign_id: str) -> dict | None:
    flash = store.get_ui_state(conn, campaign_id, "flash")
    if flash:
        conn.execute("DELETE FROM ui_state WHERE campaign_id = ? AND key = 'flash'", (campaign_id,))
    return flash


def create_app(settings: Settings) -> FastAPI:
    conn = open_database(settings.db_path)
    ui_token = settings.ui_token()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        conn.close()

    app = FastAPI(
        title="Paladin", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.settings = settings
    app.state.conn = conn
    templates = Jinja2Templates(directory=str(_HERE / "templates"))
    templates.env.globals.update(
        version=__version__,
        token=ui_token,
        VERDICT_LABELS=VERDICT_LABELS,
        EXPORT_LABELS=EXPORT_LABELS,
        REVIEW_LABELS=REVIEW_LABELS,
        VIEWS=q.VIEWS,
        DISCUSSION_COMMENT=DISCUSSION_COMMENT,
    )
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")
    from paladin.agent.api import build_router
    from paladin.agent.workspace import skill_version

    app.include_router(build_router(conn, settings.agent_token(), skill_version()))

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = urlparse("//" + (request.headers.get("host") or "")).hostname or ""
        if host and host not in LOOPBACK_HOSTS and host != "testserver":
            return Response("Hôte refusé : Paladin n'est accessible que sur la boucle locale.", status_code=421)
        if request.method in ("POST", "PUT", "DELETE"):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                o_host = urlparse(origin).hostname or ""
                if o_host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
                    return Response("Origine refusée.", status_code=403)
        return await call_next(request)

    async def _form(request: Request) -> dict[str, str]:
        form = await request.form()
        data = {k: str(v) for k, v in form.items()}
        if data.get("token") != ui_token:
            raise HTTPException(403, "Jeton d'interface invalide : recharger la page.")
        return data

    def _campaign(cid: str) -> dict[str, Any]:
        try:
            return store.get_campaign(conn, cid)
        except store.NotFoundError:
            raise HTTPException(404, "Campagne inconnue") from None

    def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx)

    # ------------------------------------------------------------------ pages

    global_flash: dict[str, Any] = {}

    def _gflash(message: str, level: str = "info", details: Any = None) -> None:
        global_flash.update({"message": message, "level": level, "details": details})

    def _pop_gflash() -> dict | None:
        out = dict(global_flash) or None
        global_flash.clear()
        return out

    @app.get("/agent", response_class=HTMLResponse)
    def agent_page(request: Request, detect: int = 0):
        from paladin.agent import connect
        from paladin.agent.workspace import DEFAULT_MODEL

        info = connect.detect(settings) if detect else None
        return render(
            request,
            "agent.html",
            info=info,
            current=settings.agent.get("model"),
            default=DEFAULT_MODEL,
            flash=_pop_gflash(),
            campaigns=store.list_campaigns(conn),
        )

    @app.post("/agent/connect")
    async def agent_connect(request: Request):
        from paladin.agent import connect

        form = await _form(request)
        model = (form.get("custom") or form.get("model") or "").strip()
        try:
            res = connect.smoke_test(settings, model)
            connect.record_smoke(settings, res)
        except ValueError as exc:
            _gflash(str(exc), "warn")
            return RedirectResponse("/agent", status_code=303)
        if res.ok:
            connect.save_model(settings, model)
            _gflash(
                f"Connecté : {model} a répondu « {res.answer} » en {res.seconds:.0f} s"
                f" (coût {res.cost_usd or 0:.4f} $). Modèle enregistré.",
                "ok",
                ["Étape suivante recommandée : « Sondage de sécurité » ci-dessous."],
            )
        else:
            _gflash(f"Échec avec {model} : {res.error}", "error", [f"→ {res.action}"])
        return RedirectResponse("/agent", status_code=303)

    @app.post("/agent/probe")
    async def agent_probe(request: Request):
        from paladin.agent.runner import AgentRunError, probe_agent

        await _form(request)
        try:
            res = probe_agent(settings)
        except AgentRunError as exc:
            _gflash(str(exc), "error", [f"→ {exc.action}"])
            return RedirectResponse("/agent", status_code=303)
        if res.ok:
            _gflash(
                "Sondage OK : l'agent n'a exécuté aucun outil hors paladin_* (shell, fichiers, réseau).",
                "ok",
                [f"Réponse du modèle : {res.model_text[:300]}"],
            )
        else:
            _gflash(
                f"ALERTE : outils interdits exécutés {res.forbidden}. Ne pas utiliser l'agent.",
                "error",
                [f"Journal : {res.log}"],
            )
        return RedirectResponse("/agent", status_code=303)

    # ------------------------------------------------- PC de travail : checklist, SSC

    @app.get("/travail", response_class=HTMLResponse)
    def travail(request: Request):
        from paladin import readiness

        items = readiness.checklist(settings, conn)
        sections: dict[str, list] = {}
        for it in items:
            sections.setdefault(it.section, []).append(it)
        done = sum(1 for it in items if it.status == readiness.OK)
        return render(
            request,
            "travail.html",
            sections=sections,
            done=done,
            total=len(items),
            fortify=settings.fortify,
            flash=_pop_gflash(),
            campaigns=store.list_campaigns(conn),
        )

    @app.post("/travail/ssc")
    async def travail_ssc(request: Request):
        from paladin.config import set_config_value
        from paladin.fortify.ssc import save_token

        form = await _form(request)
        url = form.get("url", "").strip()
        ca = form.get("ca_bundle", "").strip()
        set_config_value(settings.config_path, "fortify", "url", url)
        set_config_value(settings.config_path, "fortify", "ca_bundle", ca)
        settings.fortify.update({"url": url, "ca_bundle": ca})
        if form.get("ssc_token", "").strip():
            save_token(settings, form["ssc_token"])
        _gflash("Paramètres SSC enregistrés (jeton stocké hors du dépôt). Lancer le diagnostic.", "ok")
        return RedirectResponse("/travail#ssc", status_code=303)

    @app.post("/travail/check")
    async def travail_check(request: Request):
        from paladin import readiness
        from paladin.fortify.check import STATE_BLOCKED, run_check, write_report

        await _form(request)
        rep = run_check(settings)
        write_report(settings, rep)
        readiness.record(settings, "fortify_check", rep.state != STATE_BLOCKED, rep.state, report="/travail/rapport")
        details = [
            f"[{c.status.value}] {c.area}/{c.name} : {c.detail}"
            + (f" → {c.action}" if c.action and c.status.value != "OK" else "")
            for c in rep.checks
        ]
        _gflash(f"Diagnostic : {rep.state}", "error" if rep.state == STATE_BLOCKED else "ok", details)
        return RedirectResponse("/travail#ssc", status_code=303)

    @app.get("/travail/rapport", response_class=HTMLResponse)
    def travail_rapport(request: Request):
        reports = sorted((settings.home / "reports").glob("fortify-check-*.md"))
        text = reports[-1].read_text(encoding="utf-8") if reports else "Aucun rapport : lancer le diagnostic."
        return render(request, "report.html", text=text, path=str(reports[-1]) if reports else "")

    def _discovery_file():
        return settings.home / "run" / "ssc_discovery.json"

    @app.get("/fortify/discover", response_class=HTMLResponse)
    def fortify_discover_page(request: Request):
        import json as _json

        path = _discovery_file()
        cached = _json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return render(
            request, "discover.html", cached=cached, flash=_pop_gflash(), campaigns=store.list_campaigns(conn)
        )

    @app.post("/fortify/discover")
    async def fortify_discover_run(request: Request):
        import json as _json

        from paladin.fortify.discovery import discover
        from paladin.fortify.ssc import make_client
        from paladin.importers.fortify import FortifyError

        form = await _form(request)
        try:
            groups = discover(make_client(settings), name_filter=form.get("filter") or None)
        except FortifyError as exc:
            _gflash(str(exc), "error", [f"→ {exc.action}"])
            return RedirectResponse("/fortify/discover", status_code=303)
        path = _discovery_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _json.dumps(
                {"at": utcnow(), "filter": form.get("filter") or "", "groups": [g.as_dict() for g in groups]},
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        return RedirectResponse("/fortify/discover", status_code=303)

    @app.post("/fortify/create")
    async def fortify_create(request: Request):
        import json as _json

        from paladin.fortify.campaign import SSCCampaignError, create_campaign_from_group
        from paladin.fortify.discovery import Group, SubApp

        form = await request.form()
        if form.get("token") != ui_token:
            raise HTTPException(403, "Jeton d'interface invalide : recharger la page.")
        keys = [str(k) for k in form.getlist("group")]
        cached = _json.loads(_discovery_file().read_text(encoding="utf-8"))
        repos = [Path(x.strip()) for x in str(form.get("repos", "")).splitlines() if x.strip()]
        workbook = str(form.get("workbook", "")).strip()
        created, errors = [], []
        for g in cached["groups"]:
            if g["key"] not in keys:
                continue
            group = Group(g["key"], [SubApp(**a) for a in g["apps"]])
            try:
                created.append(
                    create_campaign_from_group(
                        settings, conn, group, repo_paths=repos, target_workbook=Path(workbook) if workbook else None
                    )
                )
            except SSCCampaignError as exc:
                errors.append(f"{g['key']} : {exc}")
        if errors:
            _gflash("Certaines entrées n'ont pas été créées.", "warn", errors)
        if len(created) == 1 and not errors:
            _flash(
                conn,
                created[0],
                "Campagne créée à partir de SSC. Étape suivante : « Importer / réimporter les sources ».",
                "ok",
            )
            return RedirectResponse(f"/c/{created[0]}", status_code=303)
        if created:
            _gflash(f"Campagnes créées : {', '.join(created)}. Ouvrir chacune et cliquer « Importer ».", "ok")
        return RedirectResponse("/fortify/discover", status_code=303)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        campaigns = store.list_campaigns(conn)
        if len(campaigns) == 1:
            return RedirectResponse(f"/c/{campaigns[0]['id']}", status_code=303)
        cards = [{**c, "counters": q.counters(conn, c["id"])} for c in campaigns]
        return render(request, "index.html", campaigns=cards, home=str(settings.home))

    @app.get("/c/{cid}", response_class=HTMLResponse)
    def dashboard(request: Request, cid: str):
        from paladin.importers import profiles

        campaign = _campaign(cid)
        tools = []
        for t in store.list_tools(conn, cid):
            run = conn.execute(
                "SELECT * FROM import_run WHERE tool_id = ? ORDER BY started_at DESC LIMIT 1", (t["id"],)
            ).fetchone()
            count = conn.execute("SELECT COUNT(*) FROM finding WHERE tool_id = ?", (t["id"],)).fetchone()[0]
            tools.append(
                {
                    **t,
                    "count": count,
                    "run": dict(run) if run else None,
                    "report": loads(run["report_json"], {}) if run else {},
                }
            )
        last_export = conn.execute(
            "SELECT * FROM export_run WHERE campaign_id = ? ORDER BY created_at DESC LIMIT 1", (cid,)
        ).fetchone()
        last = store.get_ui_state(conn, cid, "last_finding")
        return render(
            request,
            "campaign.html",
            campaign=campaign,
            counters=q.counters(conn, cid),
            tools=tools,
            pending_profiles=[p for p in profiles.list_profiles(conn, cid) if p["status"] == "proposed"],
            last_export=dict(last_export) if last_export else None,
            last_export_summary=loads(last_export["summary_json"], {}) if last_export else {},
            last_finding=last,
            last_decided=q.last_decided(conn, cid),
            flash=_pop_flash(conn, cid),
            home=str(settings.home),
            agent=agent_jobs.status(conn, cid),
        )

    @app.get("/c/{cid}/queue", response_class=HTMLResponse)
    def queue_page(request: Request, cid: str, view: str = "todo", tool: str = "", search: str = ""):
        campaign = _campaign(cid)
        rows = q.list_findings(conn, cid, view, tool or None, search or None)
        return render(
            request,
            "queue.html",
            campaign=campaign,
            rows=rows,
            view=view,
            tool=tool,
            search=search,
            tools=[t["label"] for t in store.list_tools(conn, cid)],
            counters=q.counters(conn, cid),
            flash=_pop_flash(conn, cid),
        )

    @app.get("/c/{cid}/next", response_class=HTMLResponse)
    def start_view(cid: str, view: str = "todo", tool: str = ""):
        rows = q.list_findings(conn, cid, view, tool or None, limit=1)
        if not rows:
            _flash(conn, cid, f"Rien dans la vue « {q.VIEWS.get(view, view)} ».")
            return RedirectResponse(f"/c/{cid}/queue?{urlencode({'view': view, 'tool': tool})}", status_code=303)
        return RedirectResponse(
            f"/c/{cid}/f/{rows[0]['id']}?{urlencode({'view': view, 'tool': tool})}", status_code=303
        )

    @app.get("/c/{cid}/f/{fid}", response_class=HTMLResponse)
    def card_page(request: Request, cid: str, fid: str, view: str = "todo", tool: str = ""):
        campaign = _campaign(cid)
        try:
            c = q.card(conn, cid, fid, view, tool or None)
        except LookupError:
            raise HTTPException(404, "Finding inconnu") from None
        store.set_ui_state(
            conn, cid, "last_finding", {"id": fid, "source_id": c.finding["source_id"], "view": view, "tool": tool}
        )
        prev_id = q.neighbour(conn, cid, fid, view, tool or None, -1)
        next_id = q.neighbour(conn, cid, fid, view, tool or None, +1)
        return render(
            request,
            "card.html",
            campaign=campaign,
            c=c,
            view=view,
            tool=tool,
            prev_id=prev_id,
            next_id=next_id,
            counters=q.counters(conn, cid),
            flash=_pop_flash(conn, cid),
            editor=bool(settings.editor.get("open_command")),
        )

    # ---------------------------------------------------------------- actions

    def _after(cid: str, fid: str, view: str, tool: str, move: bool) -> RedirectResponse:
        params = urlencode({"view": view, "tool": tool})
        if move:
            nxt = q.neighbour(conn, cid, fid, view, tool or None, +1)
            if nxt:
                return RedirectResponse(f"/c/{cid}/f/{nxt}?{params}", status_code=303)
            _flash(conn, cid, f"Fin de la vue « {q.VIEWS.get(view, view)} ».", "ok")
            return RedirectResponse(f"/c/{cid}/queue?{params}", status_code=303)
        return RedirectResponse(f"/c/{cid}/f/{fid}?{params}", status_code=303)

    @app.post("/c/{cid}/f/{fid}/decide")
    async def decide(request: Request, cid: str, fid: str):
        from paladin.analysis import latest_analysis

        _campaign(cid)
        form = await _form(request)
        view, tool, op = form.get("view", "todo"), form.get("tool", ""), form.get("op", "")
        try:
            revision = int(form.get("revision", "0"))
            if op == "skip":
                dec.record_decision(conn, fid, expected_revision=revision, action=DecisionAction.SKIP, author=AUTHOR)
                return _after(cid, fid, view, tool, move=True)
            if op == "investigate":
                dec.record_decision(
                    conn,
                    fid,
                    expected_revision=revision,
                    action=DecisionAction.INVESTIGATE,
                    author=AUTHOR,
                    investigation_question=form.get("question"),
                    investigation_reason=form.get("reason"),
                    analysis_id=form.get("analysis_id") or None,
                )
                _flash(conn, cid, "Mis « À investiguer » — décision enregistrée, aucune valeur Excel.", "ok")
                return _after(cid, fid, view, tool, move=True)
            if op == "decide":
                verdict = form.get("verdict") or None
                if verdict not in ("TRUE_POSITIVE", "NOT_AN_ISSUE"):
                    raise dec.DecisionError("Choisir True Positive ou Not an issue (ou « À investiguer »).")
                comment = form.get("comment", "")
                analysis = latest_analysis(conn, fid)
                accepted = (
                    analysis is not None
                    and analysis["proposed_verdict"] == verdict
                    and comment.strip() in ("", (analysis["suggested_comment"] or "").strip())
                )
                discussion = form.get("discussion") == "1" or comment.strip() == DISCUSSION_COMMENT
                dec.record_decision(
                    conn,
                    fid,
                    expected_revision=revision,
                    action=DecisionAction.ACCEPT if accepted else DecisionAction.CORRECT,
                    author=AUTHOR,
                    verdict=Verdict(verdict),
                    comment=comment,
                    analysis_id=analysis["id"] if analysis else None,
                    discussion_required=discussion,
                    discussion_reason=form.get("discussion_reason") or None,
                )
                f = conn.execute("SELECT export_state FROM finding WHERE id = ?", (fid,)).fetchone()
                _flash(
                    conn,
                    cid,
                    f"Décision enregistrée ({VERDICT_LABELS[verdict]}). {EXPORT_LABELS[f['export_state']]}.",
                    "ok",
                )
                return _after(cid, fid, view, tool, move=form.get("next") != "0")
            raise dec.DecisionError("Action inconnue.")
        except ConflictError as exc:
            _flash(conn, cid, f"{exc}", "warn")
        except dec.DecisionError as exc:
            _flash(conn, cid, str(exc), "warn")
        return _after(cid, fid, view, tool, move=False)

    @app.post("/c/{cid}/undo")
    async def undo(request: Request, cid: str):
        form = await _form(request)
        last = q.last_decided(conn, cid)
        if last is None:
            _flash(conn, cid, "Aucune décision à annuler.", "warn")
            return RedirectResponse(f"/c/{cid}", status_code=303)
        f = conn.execute("SELECT revision FROM finding WHERE id = ?", (last["finding_id"],)).fetchone()
        dec.undo_last(conn, last["finding_id"], expected_revision=f["revision"], author=AUTHOR)
        state = conn.execute("SELECT export_state FROM finding WHERE id = ?", (last["finding_id"],)).fetchone()[0]
        extra = " L'Excel déjà exporté est PÉRIMÉ : réexporter." if state == "stale" else ""
        _flash(conn, cid, f"Décision annulée sur {last['source_id']} (historique conservé).{extra}", "ok")
        params = urlencode({"view": form.get("view", "all"), "tool": form.get("tool", "")})
        return RedirectResponse(f"/c/{cid}/f/{last['finding_id']}?{params}", status_code=303)

    @app.post("/api/c/{cid}/f/{fid}/draft")
    async def draft(request: Request, cid: str, fid: str):
        if request.headers.get("x-paladin-token") != ui_token:
            return JSONResponse({"error": "jeton"}, status_code=403)
        body = await request.json()
        row = conn.execute("SELECT revision FROM finding WHERE id = ? AND campaign_id = ?", (fid, cid)).fetchone()
        if row is None:
            return JSONResponse({"error": "finding"}, status_code=404)
        if str(body.get("revision")) != str(row["revision"]):
            return JSONResponse({"error": "révision périmée"}, status_code=409)  # brouillon arrivé après une décision
        verdict = body.get("verdict") if body.get("verdict") in ("TRUE_POSITIVE", "NOT_AN_ISSUE") else None
        dec.save_draft(conn, fid, verdict, (body.get("comment") or "")[:4000])
        return JSONResponse({"saved": True})

    @app.post("/c/{cid}/agent/enqueue")
    async def agent_enqueue(request: Request, cid: str):
        await _form(request)
        n = agent_jobs.enqueue_analysis(conn, cid)
        _flash(conn, cid, f"{n} finding(s) mis en file pour l'agent." if n else "Aucun finding à mettre en file.", "ok")
        return RedirectResponse(f"/c/{cid}", status_code=303)

    @app.get("/api/c/{cid}/f/{fid}/status")
    def finding_status(cid: str, fid: str):
        row = conn.execute(
            "SELECT f.revision, f.processing_state, (SELECT MAX(seq) FROM analysis a WHERE a.finding_id = f.id) AS seq"
            " FROM finding f WHERE f.id = ? AND f.campaign_id = ?",
            (fid, cid),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Finding inconnu")
        return {
            "revision": row["revision"],
            "processing_state": row["processing_state"],
            "analysis_seq": row["seq"] or 0,
        }

    @app.post("/c/{cid}/import")
    async def run_import(request: Request, cid: str):
        from paladin.importers.pipeline import import_tool

        form = await _form(request)
        labels = [form["tool"]] if form.get("tool") else [t["label"] for t in store.list_tools(conn, cid)]
        lines, level = [], "ok"
        for label in labels:
            report = import_tool(settings, conn, cid, label)
            line = report.summary() + "".join(f" · {n}" for n in report.notes)
            if report.blocked:
                level = "warn"
                line += f" — BLOQUÉ : {report.blocked['message']}"
            if report.error:
                level = "warn"
                line += f" — {report.error['message']} → {report.error['action']}"
            lines.append(line)
        _flash(conn, cid, "Import terminé.", level, lines)
        return RedirectResponse(f"/c/{cid}", status_code=303)

    @app.get("/c/{cid}/profiles/{pid}", response_class=HTMLResponse)
    def profile_page(request: Request, cid: str, pid: str):
        from paladin.importers import profiles
        from paladin.importers.mapping import MAPPABLE_KEYS, TRANSFORMS

        campaign = _campaign(cid)
        prof = profiles.get(conn, pid)
        source_fields = _profile_source_fields(prof)
        return render(
            request,
            "profile.html",
            campaign=campaign,
            prof=prof,
            keys=MAPPABLE_KEYS,
            transforms=TRANSFORMS,
            source_fields=source_fields,
            flash=_pop_flash(conn, cid),
        )

    def _profile_source_fields(prof: dict) -> list[str]:
        fields = [spec["source"] for spec in prof["mapping"].get("fields", {}).values()]
        fields += prof["mapping"].get("comments_from", [])
        detected = prof["mapping"].get("detected_fields", [])
        return detected + sorted(set(fields) - set(detected))

    @app.post("/c/{cid}/profiles/{pid}/validate")
    async def profile_validate(request: Request, cid: str, pid: str):
        from paladin.importers import profiles
        from paladin.importers.mapping import MAPPABLE_KEYS, MappingError

        form = await _form(request)
        fields = {}
        for key in MAPPABLE_KEYS:
            src = form.get(f"src_{key}", "")
            if src:
                fields[key] = {"source": src, "transform": form.get(f"tr_{key}", "text") or "text"}
        comments = [c for c in form.get("comments_from", "").split("|") if c]
        detected = profiles.get(conn, pid)["mapping"].get("detected_fields", [])
        mapping = {"fields": fields, "constants": {}, "comments_from": comments, "detected_fields": detected}
        try:
            profiles.validate(conn, pid, mapping)
        except MappingError as exc:
            _flash(conn, cid, f"Mapping invalide : {exc}", "warn")
            return RedirectResponse(f"/c/{cid}/profiles/{pid}", status_code=303)
        _flash(conn, cid, "Profil validé. Lancer l'import pour l'appliquer.", "ok")
        return RedirectResponse(f"/c/{cid}", status_code=303)

    @app.post("/c/{cid}/export")
    async def run_export(request: Request, cid: str):
        from paladin.excel.export import export_workbook

        form = await _form(request)
        mode = "final" if form.get("mode") == "final" else "working_copy"
        result = export_workbook(settings, conn, cid, mode=mode)
        if result.status != "verified":
            _flash(
                conn, cid, f"Export non effectué ({result.status}) : {result.error}", "error", [f"→ {result.action}"]
            )
        else:
            s = result.summary
            details = [
                f"{s['cells_written']} cellule(s) écrite(s), {s['findings_up_to_date']} décision(s) à jour dans"
                " l'Excel."
            ]
            if s["blocked"]:
                details += [f"BLOQUÉ {b['sheet']} {b['source_id']} : {b['reason']}" for b in s["blocked"]]
            if s["without_target"]:
                details.append(f"{len(s['without_target'])} finding(s) sans ligne cible.")
            if s["tools_without_sheet"]:
                details.append(f"Outils sans onglet (hors export) : {', '.join(s['tools_without_sheet'])}.")
            _flash(conn, cid, f"Excel à jour : {result.destination}", "ok" if not s["blocked"] else "warn", details)
        return RedirectResponse(f"/c/{cid}", status_code=303)

    @app.post("/c/{cid}/f/{fid}/open-editor")
    async def open_editor(request: Request, cid: str, fid: str):
        from paladin.analysis import _repo_for

        await _form(request)
        command = settings.editor.get("open_command")
        row = conn.execute("SELECT * FROM finding WHERE id = ? AND campaign_id = ?", (fid, cid)).fetchone()
        if not command or row is None or not row["normalized_path"]:
            _flash(conn, cid, "Éditeur non configuré : renseigner [editor] open_command dans paladin.toml.", "warn")
        else:
            repo, rel = _repo_for(conn, row, row["normalized_path"], None)
            path = safe_repo_file(repo, rel) if repo else None
            if path is None:
                _flash(conn, cid, "Fichier introuvable dans les dépôts autorisés.", "warn")
            else:
                args = [
                    a.replace("{path}", str(path)).replace("{line}", str(row["line_number"] or 1))
                    for a in shlex.split(command, posix=True)
                ]
                subprocess.Popen(args)  # noqa: S603 — commande configurée par l'utilisateur, sans shell
        return RedirectResponse(f"/c/{cid}/f/{fid}?{urlencode({'view': 'all'})}", status_code=303)

    return app
