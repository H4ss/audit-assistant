"""Fortify SSC : client, découverte groupée, diagnostic, campagne par groupe, import via SSC fictif."""

import json
from pathlib import Path

import httpx
import pytest

from paladin import readiness, store
from paladin.config import set_config_value
from paladin.fortify import check, discovery, ssc
from paladin.fortify.campaign import SSCCampaignError, create_campaign_from_group
from paladin.fortify.fake_ssc import DEMO_TOKEN, demo_transport
from paladin.importers import fortify as fty
from paladin.importers.pipeline import import_tool, infer_scanner_root

BASE = "https://ssc.demo.invalid/ssc"


def client(transport=None, token=DEMO_TOKEN):
    return ssc.SSCClient(BASE, token, transport=transport or demo_transport())


@pytest.fixture()
def demo_ssc(settings):
    set_config_value(settings.config_path, "fortify", "url", "demo://ssc")
    settings.fortify["url"] = "demo://ssc"
    return settings


# ----------------------------------------------------------------- client


def test_api_base_and_token_variants():
    assert ssc.api_base("https://x/ssc/") == "https://x/ssc/api/v1"
    assert ssc.api_base("https://x/ssc/api/v1") == "https://x/ssc/api/v1"
    variants = ssc.token_variants("6a7b0c1d-1111-2222-3333-444455556666")
    assert len(variants) == 2 and variants[1] == "NmE3YjBjMWQtMTExMS0yMjIyLTMzMzMtNDQ0NDU1NTU2NjY2"
    assert ssc.token_variants(variants[1])[1] == variants[0]


def test_client_switches_token_encoding_and_paginates(monkeypatch):
    monkeypatch.setattr(ssc, "PAGE_LIMIT", 2)
    c = client()
    apps = c.list_applications()
    assert len(apps.data) == 6 and apps.total == 6
    assert c.token_form == "encodage alternatif"
    assert [x["status"] for x in c.calls][:2] == [401, 200]
    assert c.issue_count(10042) == 13


def test_bad_token_is_explicit():
    with pytest.raises(fty.TokenExpiredError):
        client(token="wrong").list_applications()


def test_transient_502_is_retried():
    c = client(transport=demo_transport(fail_once={"/ssc/api/v1/projects"}))
    assert len(c.list_applications().data) == 6


@pytest.mark.parametrize(("status", "error"), [(403, ssc.ForbiddenError), (404, ssc.EndpointMissingError)])
def test_http_errors_are_mapped_to_actions(status, error):
    c = client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={})))
    with pytest.raises(error) as exc:
        c.list_applications()
    assert exc.value.action


def test_tls_error_points_to_ca_bundle_never_disabling_tls():
    def boom(request):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", request=request)

    with pytest.raises(fty.FortifyError) as exc:
        client(transport=httpx.MockTransport(boom)).list_applications()
    assert "ca_bundle" in exc.value.action and "Ne jamais désactiver TLS" in exc.value.action


def test_ssc_client_works_with_strict_release_selection():
    c = client()
    assert fty.select_version(c, "SHOP.API").version_id == 10042
    with pytest.raises(fty.VersionSelectionError):
        fty.select_version(c, "CRM.PORTAL")
    with pytest.raises(fty.VersionSelectionError):
        fty.select_version(c, "TWIN.APP")


# ----------------------------------------------------------------- découverte


def test_discovery_groups_by_prefix_with_release_and_counts():
    groups = {g.key: g for g in discovery.discover(client())}
    assert list(groups) == ["CRM", "LEGACYAPP", "SHOP", "TWIN"]
    shop = groups["SHOP"]
    assert [a.app_name for a in shop.ready] == ["SHOP.API", "SHOP.BILLING"] and shop.total_findings == 16
    crm = groups["CRM"]
    assert [a.status for a in crm.apps] == ["ok", discovery.STATUS_ABSENT]
    assert crm.apps[1].other_versions == ["Release 2.1"]
    assert groups["TWIN"].apps[0].status == discovery.STATUS_AMBIGUOUS and not groups["TWIN"].ready
    assert discovery.group_key("APP2.SUBAPP1") == "APP2" and discovery.group_key("LEGACY") == "LEGACY"


# ----------------------------------------------------------------- diagnostic


def test_check_on_demo_reports_matrix_without_secrets(demo_ssc):
    rep = check.run_check(demo_ssc)
    assert rep.state == check.STATE_LIMITED and not rep.blocked
    assert any(r["champ"] == "cwe_ids" and r["disponibilité"].startswith("indisponible") for r in rep.field_matrix)
    md, js = check.write_report(demo_ssc, rep)
    text = md.read_text(encoding="utf-8") + js.read_text(encoding="utf-8")
    assert "Matrice de disponibilité" in text and DEMO_TOKEN not in text
    assert "/projectVersions/{id}/issues" in text


def test_check_blocks_without_url_or_token(settings):
    assert check.run_check(settings).state == check.STATE_BLOCKED
    settings.fortify["url"] = "https://ssc.corp/ssc"
    rep = check.run_check(settings)
    assert rep.state == check.STATE_BLOCKED and "jeton" in rep.checks[-1].name


def test_token_saved_outside_repo_and_never_in_settings_file(settings):
    path = ssc.save_token(settings, "  secret-value  ")
    assert path.parent == settings.secrets_dir and ssc.read_token(settings) == (
        "secret-value",
        "fichier secrets/fortify.token",
    )
    assert "secret-value" not in settings.config_path.read_text(encoding="utf-8")


# ----------------------------------------------------------------- campagne + import de bout en bout


def _group(key):
    return next(g for g in discovery.discover(client()) if g.key == key)


def test_group_becomes_one_input_and_imports_all_subapps(demo_ssc, conn, tmp_path):
    import shutil

    from paladin.demo import fixtures_root

    repos = tmp_path / "code"
    shutil.copytree(fixtures_root() / "repos", repos)
    cid = create_campaign_from_group(
        demo_ssc, conn, _group("SHOP"), repo_paths=[repos / "shop-api", repos / "billing-lib"]
    )
    report = import_tool(demo_ssc, conn, cid, "Fortify")
    assert report.blocked is None and report.new == 16 and report.completeness == "complete"
    rows = conn.execute(
        "SELECT application_name, COUNT(*), COUNT(DISTINCT scope_key), SUM(repo_id IS NOT NULL) FROM finding"
        " WHERE campaign_id = ? GROUP BY application_name ORDER BY 1",
        (cid,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [("SHOP.API", 13, 1, 13), ("SHOP.BILLING", 3, 1, 3)]
    roots = {r["name"]: r["scanner_roots"] for r in store.list_repos(conn, cid)}
    assert "/build/workspace/shopapp/shop-api/" in roots["shop-api"]
    assert any("Racine du scanner déduite" in n for n in report.notes)
    assert import_tool(demo_ssc, conn, cid, "Fortify").new == 0  # réimport idempotent

    from paladin.excel.export import export_workbook

    res = export_workbook(demo_ssc, conn, cid)
    assert res.status == "verified" and res.summary["rows_appended"] == {"Fortify": 16}


def test_group_without_release_is_refused(demo_ssc, conn):
    with pytest.raises(SSCCampaignError):
        create_campaign_from_group(demo_ssc, conn, _group("TWIN"))


def test_crm_group_excludes_subapp_without_release(demo_ssc, conn):
    cid = create_campaign_from_group(demo_ssc, conn, _group("CRM"))
    cfg = store.get_campaign(conn, cid)["config"]
    assert [v["application_name"] for v in cfg["tools"][0]["fortify"]["versions"]] == ["CRM.CORE"]
    assert cfg["excluded_subapps"] == [{"application_name": "CRM.PORTAL", "reason": "release absente"}]
    assert Path(cfg["target_workbook"]).is_file()  # classeur généré


def test_scanner_root_inference_refuses_ambiguity(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name / "src").mkdir(parents=True)
        (tmp_path / name / "src" / "x.py").write_text("x")
    repos = [{"id": n, "name": n, "path": str(tmp_path / n), "scanner_roots": []} for n in ("a", "b")]
    assert infer_scanner_root("/ci/build/src/x.py", repos) == (None, None, None)


# ----------------------------------------------------------------- checklist


def test_readiness_reflects_real_state(demo_ssc, conn):
    items = {i.label: i for i in readiness.checklist(demo_ssc, conn)}
    assert items["URL SSC"].status == readiness.OK
    assert items["Diagnostic « fortify check »"].status == readiness.TODO
    readiness.record(demo_ssc, "fortify_check", True, check.STATE_LIMITED)
    readiness.record(demo_ssc, "agent_smoke", True, "OK", model="zai/glm-5.3")
    items = {i.label: i for i in readiness.checklist(demo_ssc, conn)}
    assert items["Diagnostic « fortify check »"].status == readiness.OK
    assert items["Modèle connecté et testé"].status == readiness.TODO  # testé, mais pas le modèle configuré
    data = json.loads((demo_ssc.home / "run" / "status.json").read_text(encoding="utf-8"))
    assert set(data) == {"fortify_check", "agent_smoke"}
