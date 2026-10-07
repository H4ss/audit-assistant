"""Calibration sur analyses manuelles : classeur personnel, exemples / référence, aveugle, rapport, temps."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from tests.conftest import finding_by_source

from paladin import calibration, cli, groups, store
from paladin.agent import jobs
from paladin.excel import manual
from paladin.review import decisions as d
from paladin.review import memory
from paladin.web.app import create_app

F = "FFFFFFFFFFFFFFFFFFFFFFFF00"
HEADERS = ["N°", "Issue Instance", "Fichier", "Ligne", "Catégorie", "Résultat", "Justification", "Temps (min)"]
ROWS = [
    (1, F + "900001", "shop-api/app/orders.py", 12, "SQL Injection", "TP", "Concaténation SQL", 10),
    (2, F + "900002", "shop-api/app/products.py", 12, "SQL Injection", "FP", "Requête paramétrée", 8),
    (3, None, "app\\products.py", 17, "SQL Injection", "Faux positif", "Paramétrée aussi", 6),
    (4, F + "900004", "shop-api/app/search.py", 7, "XSS", "Vrai positif", "XSS réfléchi", 12),
    (5, F + "900005", "shop-api/app/profile.py", 9, "XSS", "OK", "échappé par le template", 5),
    (6, F + "900006", "shop-api/app/files.py", 11, "Path", None, "à revoir avec l'équipe", None),
    (7, "INCONNU-1", None, None, None, "TP", "?", None),
    (8, F + "900008", "billing-lib/billing/hashing.py", 7, "Hash", "FP", "clé de cache", 7),
    (9, F + "900009", "billing/tokens.py", 8, "Random", "TP", "jeton prévisible", 9),
    (10, F + "900001", None, None, None, "TP", "doublon", None),
    (11, None, "shop-api/app/logging_utils.py", 7, "Log Forging", "FP", "x", None),
    (12, F + "900007", None, None, None, None, None, None),  # pas encore analysée : ignorée
]


def _workbook(tmp_path, rows=ROWS, headers=HEADERS, name="mes analyses.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sprint 1"
    ws.append(["Analyse manuelle ShopApp — sprint 1"])
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    wb.create_sheet("Notes").append(["rien ici"])
    path = tmp_path / name
    wb.save(path)
    return path


def _status(plan):
    return {it.row: it.status for it in plan.items}


def test_own_workbook_columns_are_inferred_from_headers_and_data(demo, tmp_path):
    plan = manual.scan(demo["conn"], "demo", _workbook(tmp_path))
    assert (plan.sheet, plan.header_row) == ("Sprint 1", 2)
    assert {r: plan.column_label(r) for r in manual.ROLES} == {
        "key": "Issue Instance",  # en-tête inconnu : reconnu par ses valeurs
        "file": "Fichier",
        "line": "Ligne",
        "category": "Catégorie",
        "verdict": "Résultat",
        "comment": "Justification",
        "minutes": "Temps (min)",
    }
    assert "correspondent" in plan.reasons["key"]
    assert plan.value_map == {
        "tp": "TRUE_POSITIVE",
        "fp": "NOT_AN_ISSUE",
        "faux positif": "NOT_AN_ISSUE",
        "vrai positif": "TRUE_POSITIVE",
        "ok": "IGNORE",  # ambigu : jamais deviné
    }
    assert _status(plan) == {
        3: "importable",
        4: "importable",
        5: "importable",
        6: "importable",
        7: "non reconnu",
        8: "commentaire seul",
        9: "sans finding",
        10: "importable",
        11: "importable",
        12: "doublon",
        13: "ambigu",  # deux findings Log Forging à la même ligne
    }
    by_row = {it.row: it for it in plan.items}
    assert (by_row[5].source_id, by_row[5].matched_by) == (F + "900003", "fichier + ligne")
    assert by_row[11].matched_by == "identifiant" and by_row[11].source_id == F + "900009"


def test_import_creates_traceable_decisions_split_and_baseline(demo, tmp_path):
    conn = demo["conn"]
    path = _workbook(tmp_path)
    plan = manual.scan(conn, "demo", path, value_map={"ok": "NOT_AN_ISSUE"})
    assert _status(plan)[7] == "importable"
    res = manual.apply(conn, "demo", plan, "me")
    assert len(res.imported) == 7
    ev = d.current_decision(conn, finding_by_source(conn, F + "900003")["id"])
    assert (ev["action"], ev["authority"], ev["batch_id"], ev["verdict"]) == (
        "import",
        "import",
        res.batch_id,
        "NOT_AN_ISSUE",
    )
    assert ev["comment"] == "Paramétrée aussi" and "analyse manuelle" in ev["author"]
    # ~⅓ par verdict : 3 TP → 1, 4 Not an issue → 1
    assert res.roles["référence"] == 2 and res.roles["exemples"] == 5
    refs = conn.execute(
        "SELECT e.verdict FROM finding f JOIN decision_event e ON e.id = f.current_decision_id WHERE f.is_reference = 1"
    ).fetchall()
    assert sorted(r[0] for r in refs) == ["NOT_AN_ISSUE", "TRUE_POSITIVE"]
    assert res.baseline["minutes"] == 57 and res.baseline["findings"] == 7
    assert memory.pilot_metrics(conn, "demo")["decided_import"] == 7
    # même format au sprint suivant : lecture et traductions réutilisées, lignes déjà importées « identiques »
    again = manual.scan(conn, "demo", _workbook(tmp_path, name="sprint2.xlsx"))
    assert again.profile_reused and again.value_map["ok"] == "NOT_AN_ISSUE"
    assert _status(again)[3] == "identique"
    # annulable en bloc, comme un lot
    report = groups.undo(conn, res.batch_id, "me")
    assert len(report["annulés"]) == 7
    assert finding_by_source(conn, F + "900001")["current_decision_id"] is None


def test_existing_different_decision_is_kept_as_conflict(demo, tmp_path):
    conn = demo["conn"]
    f = finding_by_source(conn, F + "900002")
    d.record_decision(
        conn, f["id"], expected_revision=f["revision"], action="correct", author="me", verdict="TRUE_POSITIVE"
    )
    plan = manual.scan(conn, "demo", _workbook(tmp_path))
    item = next(i for i in plan.items if i.source_id == F + "900002")
    assert item.status == "conflit" and "conservé" in item.detail


def test_unreadable_or_foreign_workbooks_are_explicit(demo, tmp_path):
    conn = demo["conn"]
    with pytest.raises(manual.ManualImportError, match="introuvable"):
        manual.scan(conn, "demo", tmp_path / "absent.xlsx")
    bad = tmp_path / "x.csv"
    bad.write_text("a,b\n")
    with pytest.raises(manual.ManualImportError, match="xlsx"):
        manual.scan(conn, "demo", bad)
    with pytest.raises(manual.ManualImportError, match="Rien à importer"):
        manual.apply(conn, "demo", manual.scan(conn, "demo", _workbook(tmp_path, rows=[ROWS[6]])), "me")
    with pytest.raises(manual.ManualImportError):
        manual.stored_copy(tmp_path, "../mes analyses.xlsx")


# ----------------------------------------------------------------- aveugle


@pytest.fixture()
def api(demo, tmp_path):
    app = create_app(demo["settings"])
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    conn = app.state.conn
    rows = [ROWS[0], ROWS[1], ROWS[7]]  # 900001 TP, 900002 Not an issue, 900008 Not an issue
    plan = manual.scan(conn, "demo", _workbook(tmp_path, rows=rows))
    manual.apply(conn, "demo", plan, "me", role="example")
    for sid in ("900001", "900002"):
        calibration.set_role(conn, finding_by_source(conn, F + sid)["id"], True)
    return {"client": client, "conn": conn, "h": {"Authorization": f"Bearer {demo['settings'].agent_token()}"}, **demo}


def _claim(api):
    r = api["client"].post("/api/agent/claim", json={"worker": "t"}, headers=api["h"])
    assert r.status_code == 200, r.text
    j = r.json()
    return j, {**api["h"], "X-Lease-Token": j["lease_token"]}


def _submit(api, verdict="NOT_AN_ISSUE"):
    job, lease = _claim(api)
    ctx = api["client"].get(f"/api/agent/jobs/{job['job_id']}/context", headers=lease).json()
    body = {
        "finding_id": job["finding_id"],
        "input_revision": job["input_revision"],
        "proposed_verdict": verdict,
        "summary": "Analyse à l'aveugle.",
        "suggested_analysis_result_comment": "Parameterized query.",
        "evidence": [
            {"file": "shop-api/app/orders.py", "line_start": 12, "excerpt": "WHERE customer = '\" + customer"}
        ],
        "model_confidence": {"level": "medium", "calibrated": False},
    }
    r = api["client"].post(f"/api/agent/jobs/{job['job_id']}/proposal", json=body, headers=lease)
    assert r.status_code == 200, r.text
    return job, ctx


def test_blind_analysis_never_touches_decisions_and_hides_the_answer(api):
    conn = api["conn"]
    conn.execute("UPDATE finding SET source_comments = 'verdict humain : TP' WHERE source_id = ?", (F + "900001",))
    calibration.save_conventions(conn, "Les clés de cache ne sont jamais sensibles.", "me")
    assert calibration.enqueue_blind(conn, "demo") == 2
    assert calibration.enqueue_blind(conn, "demo") == 0  # déjà en file
    before = {s: dict(finding_by_source(conn, F + s)) for s in ("900001", "900002")}
    seen = {}
    for verdict in ("NOT_AN_ISSUE", "NOT_AN_ISSUE"):
        job, ctx = _submit(api, verdict)
        seen[job["finding_id"]] = ctx
    f1 = finding_by_source(conn, F + "900001")
    ctx1 = seen[f1["id"]]
    assert ctx1["scanner"]["source_comments"] is None  # pourrait contenir la réponse
    assert ctx1["team_conventions"]["version"] == 1 and "cache" in ctx1["team_conventions"]["text"]
    assert all(p["source_id"] not in (F + "900001", F + "900002") for p in ctx1["precedents"])
    for s in ("900001", "900002"):
        after = finding_by_source(conn, F + s)
        for k in ("current_decision_id", "review_state", "processing_state", "export_state", "revision"):
            assert after[k] == before[s][k], k
    a = conn.execute("SELECT * FROM analysis WHERE finding_id = ?", (f1["id"],)).fetchone()
    assert (a["is_blind"], a["conventions_version"]) == (1, 1)
    job_row = conn.execute("SELECT * FROM job WHERE id = ?", (a["job_id"],)).fetchone()
    assert job_row["started_at"] and job_row["finished_at"] and job_row["blind"] == 1
    r = calibration.report(conn, "demo")
    status = {x["source_id"]: x["status"] for x in r["rows"]}
    assert status == {F + "900001": "TP manqué", F + "900002": "accord"}
    assert r["rows"][0]["status"] == "TP manqué"  # l'erreur dangereuse en tête
    s = r["summary"]
    assert (s["analysed"], s["agree"], s["missed_tp"], s["refs_total"]) == (2, 1, 1, 2)
    assert any("indicatif" in w for w in r["warnings"])
    m = memory.pilot_metrics(conn, "demo")
    assert m["compared"] == 0 and m["reference_agree"] == 1  # l'aveugle ne compte pas comme revue assistée
    # nouvelle version des conventions : la référence est à refaire, mesurée séparément
    calibration.save_conventions(conn, "v2", "me")
    assert calibration.enqueue_blind(conn, "demo") == 2
    assert [v["version"] for v in calibration.report(conn, "demo")["summaries"]] == [1, 2]
    assert calibration.report(conn, "demo", version=1)["summary"]["missed_tp"] == 1


def test_shown_precedent_can_no_longer_become_reference(api):
    conn = api["conn"]
    target = finding_by_source(conn, F + "900003")  # même règle SQLi que 900002 (exemple 900008 : autre règle)
    calibration.set_role(conn, finding_by_source(conn, F + "900002")["id"], False)
    jobs.enqueue_analysis(conn, "demo", [target["id"]])
    job, lease = _claim(api)
    ctx = api["client"].get(f"/api/agent/jobs/{job['job_id']}/context", headers=lease).json()
    assert F + "900002" in [p["source_id"] for p in ctx["precedents"]]
    with pytest.raises(calibration.CalibrationError, match="biaisée"):
        calibration.set_role(conn, finding_by_source(conn, F + "900002")["id"], True)
    roles = calibration.resplit(conn, "demo")
    assert roles["gardés en exemples (déjà montrés à l'agent)"] >= 1
    assert finding_by_source(conn, F + "900002")["is_reference"] == 0


def test_rules_from_reference_cases_are_hidden_in_blind_context(api):
    from paladin import rules
    from paladin.agent.context import build_context

    conn = api["conn"]
    f2 = finding_by_source(conn, F + "900002")
    rule = rules.create_from_decision(
        conn,
        f2["id"],
        title="SQLi sûre",
        author="me",
        conditions={"tool": "Fortify", "primary_rule_id": f2["primary_rule_id"]},
    )
    rules.validate(conn, rule.id, "me")
    f1 = finding_by_source(conn, F + "900001")
    job = {"id": "x", "finding_id": f1["id"], "input_revision": f1["revision"]}
    assert build_context(conn, job)["rules"]
    assert build_context(conn, {**job, "blind": 1})["rules"] == []


def test_precedents_from_other_applications_are_labelled(demo):
    conn = demo["conn"]
    src = finding_by_source(conn, F + "900002")
    d.record_decision(
        conn,
        src["id"],
        expected_revision=src["revision"],
        action="correct",
        author="me",
        verdict="NOT_AN_ISSUE",
        comment="Paramétrée",
    )
    store.create_campaign(conn, "app2", "App 2", {})
    tool = store.add_tool(conn, "app2", "Fortify", "fortify", "Fortify")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(finding)")]
    override = {
        "id": "'f-app2'",
        "campaign_id": "'app2'",
        "tool_id": f"'{tool}'",
        "source_id": "'APP2-1'",
        "current_decision_id": "NULL",
        "review_state": "'to_review'",
        "application_name": "'App2'",
    }
    conn.execute(
        f"INSERT INTO finding ({', '.join(cols)}) SELECT {', '.join(override.get(c, c) for c in cols)}"
        " FROM finding WHERE id = ?",
        (finding_by_source(conn, F + "900003")["id"],),
    )
    target = conn.execute("SELECT * FROM finding WHERE id = 'f-app2'").fetchone()
    items = memory.precedents(conn, target)["items"]
    assert [(p["source_id"], p["basis"], p["application_name"]) for p in items] == [
        (F + "900002", "même règle, autre application", "ShopApp")
    ]


# ----------------------------------------------------------------- conventions, temps


def test_conventions_are_versioned_never_edited_in_place(conn, settings):
    assert calibration.conventions_for_agent(conn) == (None, None)
    assert calibration.save_conventions(conn, "Règle A", "me") == 1
    with pytest.raises(calibration.CalibrationError, match="identique"):
        calibration.save_conventions(conn, "Règle A\r\n", "me")
    assert calibration.save_conventions(conn, "Règle B", "me", "plus précis") == 2
    assert [h["version"] for h in calibration.conventions_history(conn)] == [2, 1]
    assert calibration.conventions_for_agent(conn)[1]["text"] == "Règle B"


def test_time_gain_compares_manual_baseline_with_measured_assisted_review(demo):
    conn = demo["conn"]
    assert calibration.time_gain(conn, "demo")["manual_min"] is None
    calibration.set_baseline(conn, "demo", 60, 10)
    t0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    for n, sid in enumerate(("900001", "900002", "900003", "900004", "900005")):
        f = finding_by_source(conn, F + sid)
        ev = d.record_decision(
            conn, f["id"], expected_revision=f["revision"], action="correct", author="me", verdict="NOT_AN_ISSUE"
        )
        conn.execute(
            "UPDATE decision_event SET created_at = ? WHERE id = ?",
            ((t0 + timedelta(minutes=2 * n)).isoformat(), ev["id"]),
        )
    g = calibration.time_gain(conn, "demo")
    assert (g["manual_min"], g["assisted_min"], g["saved_min"]) == (6.0, 1.6, 4.4)
    assert g["remaining"] == 22 - 5 and g["remaining_saved_hours"] == round(4.4 * 17 / 60, 1)
    with pytest.raises(calibration.CalibrationError):
        calibration.set_baseline(conn, "demo", 0, 3)


# ----------------------------------------------------------------- interface et CLI


def test_calibration_from_ui(demo, tmp_path):
    settings = demo["settings"]
    c, t = TestClient(create_app(settings), base_url="http://127.0.0.1:8765"), settings.ui_token()
    page = c.get("/c/demo/calibration").text
    assert "Importer mes analyses manuelles" in page and "Pas encore de jeu de référence" in page
    assert "Calibrer l'agent" in c.get("/c/demo").text
    path = _workbook(tmp_path)
    with path.open("rb") as fh:
        r = c.post("/c/demo/calibration/upload", data={"token": t}, files={"file": (path.name, fh)})
    assert "Issue Instance" in r.text and "verdict à traduire" in r.text
    stored = re.search(r'name="file" value="([^"]+)"', r.text).group(1)
    form = dict(re.findall(r'<input type="hidden" name="((?:col|vk|vv)_[^"]+)" value="([^"]*)"', r.text))
    ok_key = next(k for k, v in form.items() if k.startswith("vk_") and v == "ok")
    form["vv_" + ok_key[3:]] = "NOT_AN_ISSUE"
    preview = c.get("/c/demo/calibration/import", params={"file": stored, **form}).text
    assert "Importer 7 analyse(s)" in preview
    r = c.post(
        "/c/demo/calibration/import", data={"token": t, "file": stored, "sheet": "Sprint 1", "role": "auto", **form}
    )
    assert "7 analyse(s) manuelle(s) importée(s)" in r.text and "Temps manuel enregistré : 57.0 min" in r.text
    r = c.post("/c/demo/calibration/conventions", data={"token": t, "text": "Commentaire en anglais.", "note": ""})
    assert "Conventions v1 enregistrées" in r.text
    r = c.post("/c/demo/calibration/blind", data={"token": t})
    assert "2 analyse(s) à l&#39;aveugle en file" in r.text and "en cours" in r.text
    r = c.post("/c/demo/calibration/baseline", data={"token": t, "minutes": "90", "findings": "15"})
    assert "Temps manuel de référence enregistré" in r.text and "6.0 min" in r.text
    ref = demo["conn"].execute("SELECT id FROM finding WHERE is_reference = 1 LIMIT 1").fetchone()["id"]
    r = c.post(f"/c/demo/f/{ref}/reference", data={"token": t, "reference": "0", "back": "/c/demo/calibration#rapport"})
    assert "il devient un exemple" in r.text
    assert (
        c.post(f"/c/demo/f/{ref}/reference", data={"token": t, "reference": "1", "back": "https://evil"}).status_code
        == 200
    )
    assert "analyses manuelles importées" in c.get("/c/demo/groups").text


def test_calibration_from_cli(demo, tmp_path, capsys):
    home = str(demo["settings"].home)
    path = str(_workbook(tmp_path))
    assert cli.main(["calibration", "import", path, "--home", home]) == 0
    out = capsys.readouterr().out
    assert "Aperçu seulement" in out and "Issue Instance" in out and "'ok'" in out
    assert cli.main(["calibration", "import", path, "--home", home, "--apply", "--role", "reference"]) == 0
    assert "6 analyse(s) importée(s)" in capsys.readouterr().out
    assert cli.main(["calibration", "run", "--home", home]) == 0
    assert "6 analyse(s) à l'aveugle en file" in capsys.readouterr().out
    assert cli.main(["calibration", "baseline", "--home", home, "--minutes", "45", "--findings", "6"]) == 0
    assert cli.main(["calibration", "report", "--home", home]) == 0
    out = capsys.readouterr().out
    assert "Jeu de référence : 6 cas" in out and "7.5 min/finding" in out
    conv = tmp_path / "conv.txt"
    conv.write_text("Toujours citer la ligne.", encoding="utf-8")
    assert cli.main(["calibration", "conventions", str(conv), "--home", home]) == 0
    assert "Conventions v1" in capsys.readouterr().out
