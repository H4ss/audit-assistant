"""Pages « Prêt pour le travail », « Agent » et « Applications SSC »."""

import pytest
from fastapi.testclient import TestClient

from paladin.web.app import create_app


@pytest.fixture()
def web(settings):
    app = create_app(settings)
    return {"c": TestClient(app, base_url="http://127.0.0.1:8765"), "t": settings.ui_token(), "s": settings, "app": app}


def test_readiness_page_and_ssc_settings(web):
    c, t = web["c"], web["t"]
    page = c.get("/travail")
    assert page.status_code == 200 and "Prêt pour le PC de travail" in page.text and "à faire" in page.text
    secret = "tok-123-ne-jamais-afficher"
    r = c.post("/travail/ssc", data={"token": t, "url": "https://ssc.corp/ssc", "ca_bundle": "", "ssc_token": secret})
    assert r.status_code == 200
    from paladin.fortify.ssc import read_token

    assert read_token(web["s"])[0] == secret
    page = c.get("/travail")
    assert secret not in page.text and "fichier secrets/fortify.token" in page.text
    assert secret not in web["s"].config_path.read_text(encoding="utf-8")


def test_ssc_discovery_and_creation_from_ui(web):
    c, t = web["c"], web["t"]
    c.post("/travail/ssc", data={"token": t, "url": "demo://ssc", "ca_bundle": ""})
    c.post("/travail/check", data={"token": t})
    assert "import possible" in c.get("/travail").text
    c.post("/fortify/discover", data={"token": t, "filter": ""})
    page = c.get("/fortify/discover")
    assert "SHOP.BILLING" in page.text and "release ambiguë" in page.text
    r = c.post(
        "/fortify/create", data={"token": t, "group": "SHOP", "repos": "", "workbook": ""}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/c/shop"
    dash = c.get("/c/shop")
    assert "Campagne créée à partir de SSC" in dash.text
    r = c.post("/c/shop/import", data={"token": t})
    assert "Fortify : 16 nouveaux" in r.text


def test_agent_page_without_detection(web):
    page = web["c"].get("/agent")
    assert page.status_code == 200 and "Détecter mes modèles" in page.text
