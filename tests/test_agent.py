"""Agent : jobs avec bail, API agent (autorité « proposer »), contexte borné, espace OpenCode, runner."""

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.conftest import finding_by_source

from paladin.agent import jobs, runner, workspace
from paladin.agent.context import ContextError, read_code, search_code
from paladin.web.app import create_app

FAKE = [sys.executable, str(Path(__file__).parent / "fakes" / "fake_opencode.py")]


@pytest.fixture()
def api(demo):
    app = create_app(demo["settings"])
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    token = demo["settings"].agent_token()
    return {"client": client, "conn": app.state.conn, "h": {"Authorization": f"Bearer {token}"}, **demo}


def _claim(api):
    r = api["client"].post("/api/agent/claim", json={"worker": "t"}, headers=api["h"])
    assert r.status_code == 200, r.text
    j = r.json()
    return j, {**api["h"], "X-Lease-Token": j["lease_token"]}


# ---------------------------------------------------------------- jobs et bail


def test_enqueue_is_idempotent_and_skips_decided(api):
    conn = api["conn"]
    total = conn.execute("SELECT COUNT(*) FROM finding").fetchone()[0]
    assert jobs.enqueue_analysis(conn, "demo") == total
    assert jobs.enqueue_analysis(conn, "demo") == 0  # un seul job actif par finding
    assert jobs.status(conn, "demo")["label"] == "attente d'agent"


def test_expired_lease_is_reclaimed_and_old_token_rejected(api):
    conn = api["conn"]
    f = finding_by_source(conn, "FFFFFFFFFFFFFFFFFFFFFFFF00900001")
    jobs.enqueue_analysis(conn, "demo", [f["id"]])
    first = jobs.claim(conn, "w1")
    past = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    conn.execute("UPDATE job SET lease_expires_at = ? WHERE id = ?", (past, first["id"]))
    second = jobs.claim(conn, "w2")
    assert second["id"] == first["id"] and second["lease_token"] != first["lease_token"] and second["attempt"] == 2
    with pytest.raises(jobs.JobError):
        jobs.check_lease(conn, first["id"], first["lease_token"])
    jobs.check_lease(conn, second["id"], second["lease_token"])


def test_fail_requeues_then_errors_after_max_attempts(api):
    conn = api["conn"]
    f = finding_by_source(conn, "TB-0001")
    jobs.enqueue_analysis(conn, "demo", [f["id"]])
    for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
        job = jobs.claim(conn, "w")
        out = jobs.fail(conn, job["id"], job["lease_token"], f"échec {attempt}")
    assert out["status"] == "error" and finding_by_source(conn, "TB-0001")["processing_state"] == "error"


# ---------------------------------------------------------------- API agent


def test_agent_api_requires_agent_token(api):
    c = api["client"]
    assert c.post("/api/agent/claim").status_code == 401
    ui = {"Authorization": f"Bearer {api['settings'].ui_token()}"}
    assert c.post("/api/agent/claim", headers=ui).status_code == 401
    assert c.post("/api/agent/claim", headers=api["h"]).status_code == 204  # file vide


def test_agent_api_has_no_decision_route(api):
    from paladin.agent.api import build_router

    paths = {r.path for r in build_router(api["conn"], "t", None).routes}
    assert paths and not any(w in p for p in paths for w in ("decide", "undo", "export", "rule", "batch"))


def test_context_is_bounded_and_marks_untrusted_data(api):
    conn = api["conn"]
    jobs.enqueue_analysis(conn, "demo", [finding_by_source(conn, "FFFFFFFFFFFFFFFFFFFFFFFF00900001")["id"]])
    job, lease = _claim(api)
    ctx = api["client"].get(f"/api/agent/jobs/{job['job_id']}/context", headers=lease).json()
    assert "NON FIABLES" in ctx["notice"] and ctx["allowed_repos"] == ["billing-lib", "shop-api"]
    assert ctx["finding"]["repo"] == "shop-api" and ctx["finding"]["path_in_repo"] == "app/orders.py"
    assert ctx["classification"]["route"] == "dataflow" and ctx["code_excerpt"]["focus_line"] == 12
    assert "proposed_verdict" in json.dumps(ctx["response_schema"])
    assert str(api["settings"].home) not in json.dumps(ctx)  # aucun chemin absolu local exposé
    bad = api["client"].get(f"/api/agent/jobs/{job['job_id']}/context", headers={**api["h"], "X-Lease-Token": "x"})
    assert bad.status_code == 403


def test_code_access_is_confined_to_allowed_repos(api, tmp_path):
    conn = api["conn"]
    assert read_code(conn, "demo", "shop-api", "app/orders.py", 12, 12)["lines"][0]["n"] == 12
    for path in ("../../../../etc/passwd", "/etc/passwd", "..\\..\\x"):
        with pytest.raises(ContextError):
            read_code(conn, "demo", "shop-api", path)
    with pytest.raises(ContextError):
        read_code(conn, "demo", "not-a-repo", "x.py")
    repo = Path(conn.execute("SELECT path FROM repo WHERE name='shop-api'").fetchone()[0])
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    if os.name != "nt":
        (repo / "link.txt").symlink_to(secret)
        with pytest.raises(ContextError):
            read_code(conn, "demo", "shop-api", "link.txt")
        assert all(
            "TOP SECRET" not in r["text"] for r in search_code(conn, "demo", "shop-api", "TOP SECRET")["results"]
        )
    found = search_code(conn, "demo", "billing-lib", "def safe_join")["results"]
    assert found == [{"path": "billing/paths.py", "line": 4, "text": "def safe_join(root, name):"}]


def _proposal(job, **over):
    return {
        "finding_id": job["finding_id"],
        "input_revision": job["input_revision"],
        "proposed_verdict": "TRUE_POSITIVE",
        "summary": "Concaténation SQL.",
        "evidence": [
            {"file": "shop-api/app/orders.py", "line_start": 12, "excerpt": "WHERE customer = '\" + customer"}
        ],
        "model_confidence": {"level": "high", "calibrated": False},
        **over,
    }


def test_proposal_validation_and_storage(api):
    conn, c = api["conn"], api["client"]
    jobs.enqueue_analysis(conn, "demo", [finding_by_source(conn, "FFFFFFFFFFFFFFFFFFFFFFFF00900001")["id"]])
    job, lease = _claim(api)
    url = f"/api/agent/jobs/{job['job_id']}/proposal"
    bad = c.post(url, json=_proposal(job, proposed_verdict="MAYBE"), headers=lease)
    assert bad.status_code == 422 and bad.json()["details"]
    assert c.post(url, json=_proposal(job, finding_id="other"), headers=lease).status_code == 422
    ok = c.post(url, json={**_proposal(job), "_meta": {"model_requested": "openrouter/z-ai/glm-5.3"}}, headers=lease)
    assert ok.status_code == 200 and "pas une décision" in ok.json()["status"]
    assert ok.json()["references"][0]["status"] == "verified"
    a = conn.execute("SELECT * FROM analysis WHERE job_id = ?", (job["job_id"],)).fetchone()
    assert a["model_requested"] == "openrouter/z-ai/glm-5.3" and a["skill_version"].startswith("skill-")
    assert a["is_simulated"] == 0
    f = finding_by_source(conn, "FFFFFFFFFFFFFFFFFFFFFFFF00900001")
    assert f["processing_state"] == "proposal_ready" and f["current_decision_id"] is None  # jamais une décision
    assert c.post(url, json=_proposal(job), headers=lease).status_code == 409  # job terminé : pas de doublon


def test_too_many_invalid_answers_fail_the_job(api):
    conn, c = api["conn"], api["client"]
    jobs.enqueue_analysis(conn, "demo", [finding_by_source(conn, "TB-0001")["id"]])
    job, lease = _claim(api)
    for _ in range(3):
        r = c.post(f"/api/agent/jobs/{job['job_id']}/proposal", json={"nope": 1}, headers=lease)
    assert r.status_code == 422 and "abandonné" in r.json()["error"]
    assert jobs.get_job(conn, job["job_id"])["status"] == "pending"


# ---------------------------------------------------------------- espace OpenCode


def test_workspace_setup_is_isolated_and_idempotent(api, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    files = workspace.setup(api["settings"])
    assert {f.action for f in files} == {"créé"}
    root = workspace.workspace_dir(api["settings"])
    cfg = json.loads((root / "opencode.json").read_text(encoding="utf-8"))
    assert cfg["model"] == "openrouter/z-ai/glm-5.3" and cfg["permission"]["*"] == "deny"
    assert (root / ".opencode" / "agents" / "paladin-analyst.md").read_text(encoding="utf-8").count('"*": deny') == 2
    assert {f.action for f in workspace.setup(api["settings"])} == {"inchangé"}
    assert not (tmp_path / "fakehome" / ".config" / "opencode").exists()  # config globale intacte
    conn_file = workspace.write_connection(api["settings"], "http://127.0.0.1:1", "openrouter/z-ai/glm-5.3", "demo")
    if os.name != "nt":
        assert oct(conn_file.stat().st_mode & 0o777) == "0o600"


def test_parse_opencode_output():
    out = "\n".join(
        [
            json.dumps({"type": "text", "text": "x"}),
            json.dumps(
                {"type": "step-finish", "cost": 0.01, "tokens": {"input": 10, "output": 5, "cache": {"read": 3}}}
            ),
            json.dumps(
                {"part": {"type": "step-finish", "cost": 0.02, "tokens": {"input": 1, "output": 1}}, "modelID": "m"}
            ),
            "not json",
        ]
    )
    p = runner.parse_opencode_output(out)
    assert p["cost_usd"] == pytest.approx(0.03) and p["tokens"]["input"] == 11 and p["tokens"]["cache_read"] == 3
    assert p["model"] == "m"


# ---------------------------------------------------------------- runner (chaîne complète, faux opencode)


def test_runner_full_chain_with_fake_opencode(api, monkeypatch):
    conn = api["conn"]
    ids = [finding_by_source(conn, s)["id"] for s in ("FFFFFFFFFFFFFFFFFFFFFFFF00900001", "TB-0001")]
    jobs.enqueue_analysis(conn, "demo", ids)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setattr(runner, "openrouter_usage", lambda key: None)  # pas d'appel réseau : coût lu dans la sortie
    report = runner.run_agent(
        api["settings"], conn, "demo", max_jobs=5, budget_usd=1.0, opencode_cmd=FAKE, printer=lambda s: None
    )
    assert [o.status for o in report.outcomes] == ["proposition reçue", "proposition reçue"]
    assert report.stopped == "plus aucun job en attente"
    assert report.spent_usd == pytest.approx(0.0024)
    assert conn.execute("SELECT COUNT(*) FROM analysis WHERE is_simulated = 0").fetchone()[0] == 2
    assert jobs.status(conn, "demo")["cost_usd"] == pytest.approx(0.0024)
    assert conn.execute("SELECT COUNT(*) FROM decision_event").fetchone()[0] == 0


def test_runner_releases_job_when_session_ends_without_proposal(api, monkeypatch):
    conn = api["conn"]
    jobs.enqueue_analysis(conn, "demo", [finding_by_source(conn, "TB-0001")["id"]])
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("FAKE_OPENCODE_MODE", "silent")
    monkeypatch.setattr(runner, "openrouter_usage", lambda key: None)
    report = runner.run_agent(
        api["settings"], conn, "demo", max_jobs=1, budget_usd=1.0, opencode_cmd=FAKE, printer=lambda s: None
    )
    assert report.outcomes[0].status == "échec"
    assert jobs.status(conn, "demo")["pending"] == 1  # remis en file, bail libéré


def test_runner_respects_budget_with_provider_measure(api, monkeypatch):
    conn = api["conn"]
    jobs.enqueue_analysis(conn, "demo")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    usage = iter([0.0, 0.08, 0.16])
    monkeypatch.setattr(runner, "openrouter_usage", lambda key: next(usage))
    report = runner.run_agent(
        api["settings"], conn, "demo", max_jobs=10, budget_usd=0.15, opencode_cmd=FAKE, printer=lambda s: None
    )
    assert len(report.outcomes) == 1 and report.spent_usd == pytest.approx(0.08)  # mesuré chez le fournisseur
    assert "plafond" in report.stopped


def test_runner_works_without_provider_key(api, monkeypatch):
    """Plug and play : l'authentification du modèle est celle de l'OpenCode du poste."""
    conn = api["conn"]
    jobs.enqueue_analysis(conn, "demo", [finding_by_source(conn, "TB-0001")["id"]])
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    report = runner.run_agent(
        api["settings"], conn, "demo", max_jobs=1, budget_usd=1.0, opencode_cmd=FAKE, printer=lambda s: None
    )
    assert report.outcomes[0].status == "proposition reçue" and report.cost_source == "sortie OpenCode"


def test_runner_uses_client_cost_when_provider_counter_lags(api, monkeypatch):
    conn = api["conn"]
    jobs.enqueue_analysis(conn, "demo", [finding_by_source(conn, "TB-0001")["id"]])
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setattr(runner, "openrouter_usage", lambda key: 0.5)  # compteur figé (retard du fournisseur)
    report = runner.run_agent(
        api["settings"], conn, "demo", max_jobs=1, budget_usd=1.0, opencode_cmd=FAKE, printer=lambda s: None
    )
    assert report.spent_usd == pytest.approx(0.0012)  # coût rapporté par OpenCode, jamais 0 par défaut
    job = conn.execute("SELECT usage_json FROM job WHERE finding_id = ?", (finding_by_source(conn, "TB-0001")["id"],))
    assert json.loads(job.fetchone()[0]) == {"input": 1000, "output": 200}  # tokens conservés après le coût


def test_workspace_removes_stale_v1_tools(api):
    root = workspace.workspace_dir(api["settings"])
    stale = root / ".opencode" / "tools" / "paladin.ts"
    stale.parent.mkdir(parents=True)
    stale.write_text("ancien format V1")
    actions = {f.path.name: f.action for f in workspace.setup(api["settings"])}
    assert not stale.exists() and actions["paladin.ts"] in ("supprimé", "créé")
    assert (root / ".opencode" / "plugins" / "paladin.ts").exists()


@pytest.mark.parametrize(("mode", "ok"), [("probe_ok", True), ("probe_bad", False)])
def test_probe_flags_any_forbidden_tool_execution(api, monkeypatch, mode, ok):
    monkeypatch.setenv("FAKE_OPENCODE_MODE", mode)
    res = runner.probe_agent(api["settings"], opencode_cmd=FAKE)
    assert res.ok is ok
    assert res.forbidden == ([] if ok else ["bash"])  # un refus ("error") n'est pas une exécution
