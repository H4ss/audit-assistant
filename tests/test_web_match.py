"""Pages « Rapprochement » et « Nouvel onglet »."""

import re

import pytest
from fastapi.testclient import TestClient

from paladin.importers import profiles
from paladin.importers.pipeline import import_tool
from paladin.web.app import create_app


@pytest.fixture()
def web(demo):
    profiles.validate(demo["conn"], demo["reports"]["ToolC"].blocked["profile_id"])
    import_tool(demo["settings"], demo["conn"], "demo", "ToolC")
    app = create_app(demo["settings"])
    return {
        "c": TestClient(app, base_url="http://127.0.0.1:8765"),
        "t": demo["settings"].ui_token(),
        "conn": app.state.conn,
    }


def test_match_flow_from_ui(web):
    c, t = web["c"], web["t"]
    assert "Préparer le rapprochement" in c.get("/c/demo/match").text
    r = c.post("/c/demo/match/run", data={"token": t})
    assert "Fortify ↔ ToolB : 11 nouveau(x) candidat(s)" in r.text and "Unknown" in r.text
    page = c.get("/c/demo/match").text
    rid = re.search(r"/c/demo/match/([0-9a-f]{32})", page).group(1)
    card = c.get(f"/c/demo/match/{rid}").text
    rev = re.search(r'name="revision" value="(\d+)"', card).group(1)
    r = c.post(f"/c/demo/match/{rid}/decide", data={"token": t, "revision": rev, "op": "same"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] != f"/c/demo/match/{rid}"  # candidat suivant
    stale = c.post(f"/c/demo/match/{rid}/decide", data={"token": t, "revision": rev, "op": "different"})
    assert "Ce lien a changé" in stale.text
    batch_ids = re.findall(r'name="rid" value="([0-9a-f]{32})"', c.get("/c/demo/match").text)
    r = c.post("/c/demo/match/batch", data={"token": t, "rid": batch_ids})
    assert f"{len(batch_ids)} lien(s) confirmé(s) en lot" in r.text


def test_schema_page_and_validation(web):
    c, t = web["c"], web["t"]
    dash = c.get("/c/demo").text
    assert "/c/demo/tools/ToolC/schema" in dash
    page = c.get("/c/demo/tools/ToolC/schema").text
    assert "Nouvel onglet pour ToolC" in page and "hardcoded-credential" in page
    r = c.post("/c/demo/tools/ToolC/schema", data={"token": t, "sheet_name": "ToolC", "keep_category": "1"})
    assert "Onglet « ToolC » validé (v1)" in r.text
    r = c.post("/c/demo/export", data={"token": t, "mode": "working_copy"})
    assert "Excel à jour" in r.text


def test_missing_comparative_columns_button(web):
    c, t = web["c"], web["t"]
    c.post("/c/demo/match/run", data={"token": t})
    page = c.get("/c/demo/match").text
    assert "Fortify : Found in ToolC, criticality in ToolC" in page
    r = c.post("/c/demo/match/extensions", data={"token": t})
    assert "Colonnes comparatives ajoutées" in r.text and "Colonnes comparatives absentes" not in r.text
