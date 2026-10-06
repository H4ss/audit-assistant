"""Interface locale : sécurité, parcours de revue, import, profil, export."""

import re

import pytest
from fastapi.testclient import TestClient

from paladin.demo import add_simulated_proposals
from paladin.web.app import create_app
from tests.conftest import finding_by_source

F1 = "FFFFFFFFFFFFFFFFFFFFFFFF00900001"


@pytest.fixture()
def web(demo):
    add_simulated_proposals(demo["conn"])
    app = create_app(demo["settings"])
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return {"client": client, "conn": app.state.conn, "token": demo["settings"].ui_token()}


def _card(web, sid, view="all"):
    f = finding_by_source(web["conn"], sid)
    return f, web["client"].get(f"/c/demo/f/{f['id']}?view={view}")


def _decide(web, sid, view="all", **fields):
    f = finding_by_source(web["conn"], sid)
    data = {"token": web["token"], "revision": str(f["revision"]), "view": view, "tool": "", "op": "decide", **fields}
    return web["client"].post(f"/c/demo/f/{f['id']}/decide", data=data, follow_redirects=False)


def _events(web, sid):
    f = finding_by_source(web["conn"], sid)
    return web["conn"].execute("SELECT * FROM decision_event WHERE finding_id = ? ORDER BY seq", (f["id"],)).fetchall()


def test_foreign_host_is_refused(web):
    r = web["client"].get("/c/demo", headers={"host": "evil.example:8765"})
    assert r.status_code == 421


def test_post_requires_ui_token_and_local_origin(web):
    f = finding_by_source(web["conn"], F1)
    url = f"/c/demo/f/{f['id']}/decide"
    base = {"revision": str(f["revision"]), "op": "decide", "verdict": "TRUE_POSITIVE"}
    assert web["client"].post(url, data={**base, "token": "wrong"}).status_code == 403
    r = web["client"].post(url, data={**base, "token": web["token"]}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert _events(web, F1) == []


def test_agent_token_cannot_decide(web, demo):
    f = finding_by_source(web["conn"], F1)
    r = web["client"].post(f"/c/demo/f/{f['id']}/decide", data={
        "token": demo["settings"].agent_token(), "revision": str(f["revision"]), "op": "decide",
        "verdict": "TRUE_POSITIVE"})
    assert r.status_code == 403


def test_card_shows_proposal_evidence_and_simulation(web):
    _, r = _card(web, F1)
    assert r.status_code == 200
    assert "proposition simulée" in r.text and "référence vérifiée" in r.text
    assert "non calibrée" in r.text
    _, bad = _card(web, "FFFFFFFFFFFFFFFFFFFFFFFF00900010")
    assert "référence invalide" in bad.text
    _, notrace = _card(web, "FFFFFFFFFFFFFFFFFFFFFFFF00900003")
    assert "trace indisponible" in notrace.text
    _, code = _card(web, "FFFFFFFFFFFFFFFFFFFFFFFF00900011")  # sans proposition : code et checklist
    assert "Aucune proposition" in code.text and 'class="hl"' in code.text


def test_accept_proposal_records_accept_and_moves_on(web):
    r = _decide(web, F1, view="ready", verdict="TRUE_POSITIVE", comment="")
    assert r.status_code == 303 and "/f/" in r.headers["location"] and "view=ready" in r.headers["location"]
    ev = _events(web, F1)
    assert [e["action"] for e in ev] == ["accept"] and ev[0]["analysis_id"]


def test_comment_only_correction_is_a_correction(web):
    _decide(web, F1, verdict="TRUE_POSITIVE", comment="Concaténation directe.")
    ev = _events(web, F1)[-1]
    assert ev["action"] == "correct" and ev["verdict"] == "TRUE_POSITIVE" and ev["comment"] == "Concaténation directe."


def test_discussion_with_not_an_issue(web):
    sid = "FFFFFFFFFFFFFFFFFFFFFFFF00900007"
    _decide(web, sid, verdict="NOT_AN_ISSUE", comment="security appetite to be discussed", discussion="1",
            discussion_reason="secret de test")
    ev = _events(web, sid)[-1]
    assert ev["verdict"] == "NOT_AN_ISSUE" and ev["comment"] == "security appetite to be discussed"
    assert ev["discussion_required"] == 1 and ev["discussion_reason"] == "secret de test"


def test_double_submit_records_one_decision(web):
    f = finding_by_source(web["conn"], F1)
    data = {"token": web["token"], "revision": str(f["revision"]), "op": "decide", "verdict": "TRUE_POSITIVE",
            "view": "all"}
    web["client"].post(f"/c/demo/f/{f['id']}/decide", data=data, follow_redirects=False)
    r = web["client"].post(f"/c/demo/f/{f['id']}/decide", data=data, follow_redirects=False)
    assert len(_events(web, F1)) == 1
    page = web["client"].get(r.headers["location"])
    assert "Révision périmée" in page.text


def test_missing_verdict_is_refused_with_guidance(web):
    r = _decide(web, F1, comment="x")
    page = web["client"].get(r.headers["location"])
    assert "Choisir True Positive ou Not an issue" in page.text and _events(web, F1) == []


def test_investigate_and_undo(web):
    sid = "FFFFFFFFFFFFFFFFFFFFFFFF00900006"
    f = finding_by_source(web["conn"], sid)
    web["client"].post(f"/c/demo/f/{f['id']}/decide", data={
        "token": web["token"], "revision": str(f["revision"]), "op": "investigate", "view": "all",
        "question": "safe_join et liens symboliques ?", "reason": "protection hors dépôt"})
    assert finding_by_source(web["conn"], sid)["review_state"] == "investigating"
    r = web["client"].post("/c/demo/undo", data={"token": web["token"], "view": "all"}, follow_redirects=False)
    assert r.status_code == 303
    after = finding_by_source(web["conn"], sid)
    assert after["review_state"] == "to_review" and len(_events(web, sid)) == 2


def test_queue_does_not_reorder_under_cursor(web):
    from paladin.review import queue as q

    rows = q.list_findings(web["conn"], "demo", "todo")
    first, second = rows[0], rows[1]
    r = _decide(web, first["source_id"], view="todo", verdict="TRUE_POSITIVE")
    assert r.headers["location"].startswith(f"/c/demo/f/{second['id']}")


def test_draft_api_requires_token_and_restores(web):
    f = finding_by_source(web["conn"], F1)
    url = f"/api/c/demo/f/{f['id']}/draft"
    assert web["client"].post(url, json={"comment": "x"}).status_code == 403
    hdr = {"x-paladin-token": web["token"]}
    assert web["client"].post(url, json={"verdict": "NOT_AN_ISSUE", "comment": "brouillon persistant",
                                         "revision": f["revision"]}, headers=hdr).status_code == 200
    stale = web["client"].post(url, json={"comment": "trop tard", "revision": f["revision"] - 1}, headers=hdr)
    assert stale.status_code == 409
    _, page = _card(web, F1)
    assert "brouillon persistant" in page.text


def test_untrusted_content_is_escaped(web):
    f = finding_by_source(web["conn"], F1)
    web["conn"].execute("UPDATE finding SET category = ? WHERE id = ?", ("<script>alert(1)</script>", f["id"]))
    _, page = _card(web, F1)
    assert "<script>alert(1)</script>" not in page.text and "&lt;script&gt;" in page.text


def test_profile_validation_import_and_export_from_ui(web):
    c = web["client"]
    dash = c.get("/c/demo")
    pid = re.search(r"/c/demo/profiles/([0-9a-f]{32})", dash.text).group(1)
    page = c.get(f"/c/demo/profiles/{pid}")
    assert "Location" in page.text and "location_line" in page.text
    data = {"token": web["token"], "src_source_id": "Ref", "src_category": "Check",
            "src_full_filename": "Location", "tr_full_filename": "location_path",
            "src_line_number": "Location", "tr_line_number": "location_line",
            "src_criticality_raw": "Severity", "src_description": "Details"}
    c.post(f"/c/demo/profiles/{pid}/validate", data=data)
    r = c.post("/c/demo/import", data={"token": web["token"], "tool": "ToolC"})
    assert "ToolC : 5 nouveaux" in r.text
    _decide(web, "TB-0001", verdict="TRUE_POSITIVE")
    r = c.post("/c/demo/export", data={"token": web["token"], "mode": "working_copy"})
    assert "Excel à jour" in r.text and "ToolC" in r.text  # outil sans onglet signalé


def test_divergent_card_shows_both_values(web):
    _, page = _card(web, "TB-0003")
    assert page.status_code == 200
    assert "Sources en désaccord" in page.text and "High" in page.text and "Critical" in page.text


def test_every_card_renders(web):
    ids = [r["id"] for r in web["conn"].execute("SELECT id FROM finding")]
    for fid in ids:
        assert web["client"].get(f"/c/demo/f/{fid}?view=all").status_code == 200, fid
    for view in ("todo", "ready", "missing", "investigating", "reexam", "validated", "all"):
        assert web["client"].get(f"/c/demo/queue?view={view}").status_code == 200
