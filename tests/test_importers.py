"""Imports multi-entrées : MD, Excel/CSV, SARIF, Fortify, rapprochement intra-outil, identité."""

import json
from pathlib import Path

import pytest
from openpyxl import Workbook
from tests.conftest import finding_by_source

from paladin.classify import classify
from paladin.contracts import Completeness, ReviewState
from paladin.demo import fixtures_root
from paladin.importers import fortify as fty
from paladin.importers.mapping import apply_mapping, propose_mapping
from paladin.importers.markdown import read_markdown
from paladin.importers.pipeline import import_tool
from paladin.importers.sarif import SARIF_MAPPING, read_sarif
from paladin.importers.tabular import read_csv, read_excel

ROOT = fixtures_root()

# ----------------------------------------------------------------- Markdown


def test_heading_kv_profile_reads_findings_with_offsets():
    path = ROOT / "toolb" / "toolb_details.md"
    read = read_markdown(path, "heading-kv-v1", {"ignore_sections": ["Scan statistics"]})
    assert len(read.records) == 8
    assert read.completeness == Completeness.COMPLETE
    assert read.scope == {"application_name": "ShopApp", "version_name": "release"}
    assert [i.reason for i in read.ignored] == ["section ignorée par le profil"]
    first = read.records[0]
    start, end = (int(x) for x in first.locator.split("@")[1].split("-"))
    assert path.read_text(encoding="utf-8")[start:end].startswith("## TB-0001")
    assert "Description" in first.sections


def test_md_unknown_section_makes_import_partial():
    read = read_markdown(ROOT / "toolb" / "toolb_details.md", "heading-kv-v1")  # section non déclarée ignorée
    assert read.completeness == Completeness.PARTIAL
    assert any("titre sans identifiant" in u.reason for u in read.unrecognized)


def test_table_profile_flags_malformed_row_and_extra_section():
    read = read_markdown(ROOT / "toolc" / "toolc_report.md", "table-v1")
    assert len(read.records) == 5
    assert read.completeness == Completeness.PARTIAL
    reasons = " | ".join(u.reason for u in read.unrecognized)
    assert "mal formée" in reasons and "sans tableau" in reasons


def test_table_escaped_pipe(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("| Ref | Details |\n|---|---|\n| X-1 | a \\| b |\n", encoding="utf-8")
    read = read_markdown(p, "table-v1")
    assert read.records[0].fields["Details"] == "a | b"


def test_unknown_md_profile_rejected(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_markdown(p, "anything-goes")


# ------------------------------------------------------- Inférence multi-entrées


def _write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_french_csv_mapping_inference(tmp_path):
    p = _write_csv(
        tmp_path / "toold.csv",
        "Référence;Titre;Gravité;Emplacement;Règle;CWE;Commentaires;analysis result\n"
        "D-1;Injection SQL;Haute;shop-api/app/orders.py:12;SQLI-1;CWE-89;vu en revue;\n"
        "D-2;XSS;Moyenne;shop-api/app/search.py:7;XSS-2;79;;\n",
    )
    read = read_csv(p)
    prop = propose_mapping(read.field_names, read.records)
    f = prop.fields
    assert f["source_id"]["source"] == "Référence"
    assert f["category"]["source"] == "Titre"
    assert f["criticality_raw"]["source"] == "Gravité"
    assert f["full_filename"] == {"source": "Emplacement", "transform": "location_path"}
    assert f["line_number"] == {"source": "Emplacement", "transform": "location_line"}
    assert f["cwe_ids"]["transform"] == "cwe_list"
    assert prop.comments_from == ["Commentaires"]
    assert "analysis result" in prop.unmapped  # colonne cible, jamais une source
    nf = apply_mapping(read.records[1], prop.as_mapping(), "ToolD")
    assert (nf.full_filename, nf.line_number, nf.cwe_ids) == ("shop-api/app/search.py", 7, ["CWE-79"])


def test_target_comparative_columns_never_mapped():
    from paladin.importers.records import RawRecord

    names = ["ID", "Severity", "criticality in Fortify", "Found in Fortify"]
    prop = propose_mapping(names, [RawRecord({"ID": "1", "Severity": "High", "criticality in Fortify": "Low"}, "l")])
    assert prop.fields["criticality_raw"]["source"] == "Severity"
    assert {"criticality in Fortify", "Found in Fortify"} <= set(prop.unmapped)


def test_separate_competitor_excel(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(["Rapport ToolE"])  # ligne de titre avant les en-têtes
    ws.append(["Issue ID", "Vulnerability", "Severity", "File", "Line"])
    ws.append(["E-1", "SQL Injection", "High", "shop-api/app/orders.py", 12])
    wb.save(tmp_path / "toole.xlsx")
    read = read_excel(tmp_path / "toole.xlsx")
    assert read.scope["header_row"] == 2
    prop = propose_mapping(read.field_names, read.records)
    nf = apply_mapping(read.records[0], prop.as_mapping(), "ToolE")
    assert (nf.source_id, nf.category, nf.line_number) == ("E-1", "SQL Injection", 12)


def test_sarif_reader(tmp_path):
    doc = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ToolS",
                        "rules": [
                            {
                                "id": "py/sql-injection",
                                "name": "SqlInjection",
                                "properties": {"tags": ["security", "external/cwe/cwe-089"]},
                            }
                        ],
                    }
                },
                "results": [
                    {
                        "ruleId": "py/sql-injection",
                        "level": "error",
                        "message": {"text": "SQLi"},
                        "partialFingerprints": {"primaryLocationLineHash": "abc"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "shop-api/app/orders.py"},
                                    "region": {"startLine": 12},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }
    p = tmp_path / "r.sarif"
    p.write_text(json.dumps(doc), encoding="utf-8")
    read = read_sarif(p)
    nf = apply_mapping(read.records[0], SARIF_MAPPING, "ToolS")
    assert (nf.source_id, nf.cwe_ids, nf.line_number, nf.primary_location) == ("abc", ["CWE-89"], 12, "orders.py")


def test_classification_basis_is_traceable():
    assert classify(["CWE-89"], "whatever").basis == "cwe:89"
    c = classify([], "HTML5: Missing Content Security Policy")
    assert (c.family, c.route) == ("security_config", "config")
    unknown = classify([], "Something odd")
    assert unknown.family is None and unknown.basis is None


# ------------------------------------------------------------------ Fortify


def test_release_selection_nominal_absent_ambiguous():
    src = fty.FixtureFortifySource(ROOT / "fortify")
    choice = fty.select_version(src, "ShopApp")
    assert (choice.version_id, choice.version_name) == (10042, "release")
    with pytest.raises(fty.VersionSelectionError, match="absente"):
        fty.select_version(src, "LegacyPortal")
    with pytest.raises(fty.VersionSelectionError, match="ambiguë"):
        fty.select_version(src, "TwinApp")
    assert fty.select_version(src, "TwinApp", version_id=30002).version_id == 30002
    with pytest.raises(fty.VersionSelectionError):
        fty.select_version(src, "ShopApp", version_id=10043)  # "dev" : jamais choisie


def test_collect_all_pages_with_duplicate(tmp_path):
    src = fty.FixtureFortifySource(ROOT / "fortify")
    res = fty.collect(src, fty.select_version(src, "ShopApp"), tmp_path / "cap")
    assert res.read.completeness == Completeness.COMPLETE
    assert res.manifest["expected_total"] == 13 and res.manifest["unique_ids"] == 13
    assert len(res.manifest["transport_duplicates"]) == 1
    assert all(e["sha256"] for e in res.manifest["captures"])
    assert json.loads(res.manifest_path.read_text(encoding="utf-8"))["immutable_snapshot"] is False


def test_failed_page_is_partial_then_resumable(tmp_path):
    src = fty.FixtureFortifySource(ROOT / "fortify", faults={"fail_pages_at": [8]})
    choice = fty.select_version(src, "ShopApp")
    res = fty.collect(src, choice, tmp_path / "cap1")
    assert res.read.completeness == Completeness.PARTIAL
    assert res.manifest["unique_ids"] == 8 and res.error is not None
    resumed = fty.collect(src, choice, tmp_path / "cap2", resume_manifest=res.manifest)
    assert resumed.read.completeness == Completeness.COMPLETE
    assert resumed.manifest["unique_ids"] == 13


def test_expired_token_keeps_partial_collection(tmp_path):
    src = fty.FixtureFortifySource(ROOT / "fortify", faults={"expire_token_after_calls": 3})
    res = fty.collect(src, fty.select_version(src, "ShopApp"), tmp_path / "cap")
    assert res.read.completeness == Completeness.PARTIAL
    assert "Renouveler le jeton" in res.error.action


def test_fortify_import_keeps_both_categories_and_release_id(demo):
    f = finding_by_source(demo["conn"], "FFFFFFFFFFFFFFFFFFFFFFFF00900001")
    assert f["category"] == "SQL Injection"
    assert f["fortify_category"] == "Input Validation and Representation"
    assert (f["version_name"], f["version_source_id"]) == ("release", "10042")
    assert f["normalized_path"] == "shop-api/app/orders.py"
    assert f["full_filename"] == "/build/workspace/shopapp/shop-api/app/orders.py"
    assert demo["conn"].execute("SELECT COUNT(*) FROM finding WHERE source_id LIKE 'EEEE%'").fetchone()[0] == 0  # dev
    no_line = finding_by_source(demo["conn"], "FFFFFFFFFFFFFFFFFFFFFFFF00900013")
    assert no_line["line_number"] is None
    assert (
        json.loads(finding_by_source(demo["conn"], "FFFFFFFFFFFFFFFFFFFFFFFF00900003")["details_json"])[
            "trace_available"
        ]
        is False
    )


def test_absent_release_blocks_import(demo):
    conn, settings = demo["conn"], demo["settings"]
    cfg = json.loads(conn.execute("SELECT config_json FROM campaign WHERE id='demo'").fetchone()[0])
    cfg["tools"][0]["fortify"]["application_name"] = "LegacyPortal"
    conn.execute("UPDATE campaign SET config_json = ? WHERE id = 'demo'", (json.dumps(cfg),))
    before = conn.execute("SELECT COUNT(*) FROM finding").fetchone()[0]
    report = import_tool(settings, conn, "demo", "Fortify")
    assert report.blocked and "absente" in report.blocked["message"]
    assert conn.execute("SELECT COUNT(*) FROM finding").fetchone()[0] == before


# ---------------------------------------------- Rapprochement intra-outil et identité


def test_excel_md_counters_and_divergence(demo):
    r = demo["reports"]["ToolB"]
    assert (r.matched, r.inventory_only, r.details_only, r.divergent) == (7, 1, 1, 1)
    conn = demo["conn"]
    tb3 = finding_by_source(conn, "TB-0003")
    assert json.loads(tb3["divergent_fields_json"]) == ["criticality_raw"]
    values = {
        row["value_json"]
        for row in conn.execute(
            "SELECT value_json FROM field_value WHERE finding_id = ? AND field = 'criticality_raw'", (tb3["id"],)
        )
    }
    assert values == {'"High"', '"Critical"'}  # les deux valeurs originales conservées
    assert tb3["category"] == "Reflected cross-site scripting"  # enrichie par le MD
    tb9 = json.loads(finding_by_source(conn, "TB-0009")["details_json"])
    assert tb9["match"]["state"] == "details_only"
    tb8 = json.loads(finding_by_source(conn, "TB-0008")["details_json"])
    assert tb8["preexisting_analyst_values"]["analysis result"] == "Not an issue"


def test_reimport_twice_creates_no_duplicates(demo):
    conn, settings = demo["conn"], demo["settings"]
    count = conn.execute("SELECT COUNT(*) FROM finding").fetchone()[0]
    for tool in ("Fortify", "ToolB"):
        r = import_tool(settings, conn, "demo", tool)
        assert r.new == 0 and r.updated == 0
    assert conn.execute("SELECT COUNT(*) FROM finding").fetchone()[0] == count
    assert conn.execute("SELECT COUNT(*) FROM decision_event").fetchone()[0] == 0


def test_changed_source_marks_validated_finding_for_reexam(demo, tmp_path):
    from paladin.review.decisions import record_decision

    conn, settings = demo["conn"], demo["settings"]
    f = finding_by_source(conn, "TB-0001")
    record_decision(
        conn, f["id"], expected_revision=f["revision"], action="accept", author="me", verdict="TRUE_POSITIVE"
    )
    md = settings.campaign_dir("demo") / "inputs" / "toolb" / "toolb_details.md"
    md.write_text(md.read_text(encoding="utf-8").replace("- **Line**: 12", "- **Line**: 13", 1), encoding="utf-8")
    r = import_tool(settings, conn, "demo", "ToolB")
    assert r.updated == 1 and r.reexam_required == 1
    after = finding_by_source(conn, "TB-0001")
    assert after["review_state"] == ReviewState.REEXAM_REQUIRED
    assert after["current_decision_id"] is not None  # la décision humaine n'est pas effacée


def test_same_id_different_content_is_a_collision_not_a_merge(settings, conn, tmp_path):
    from paladin import store

    md = tmp_path / "dup.md"
    md.write_text(
        "| Ref | Check | Location |\n|---|---|---|\n| X-1 | a | f.py:1 |\n| X-1 | b | g.py:2 |\n", encoding="utf-8"
    )
    cfg = {
        "id": "c",
        "target_workbook": "none.xlsx",
        "tools": [
            {
                "label": "ToolX",
                "kind": "md",
                "sheet_name": None,
                "sources": [
                    {
                        "role": "findings",
                        "kind": "md",
                        "path": str(md),
                        "profile": "table-v1",
                        "mapping": {
                            "fields": {
                                "source_id": {"source": "Ref"},
                                "category": {"source": "Check"},
                                "full_filename": {"source": "Location", "transform": "location_path"},
                            }
                        },
                    }
                ],
            }
        ],
    }
    store.create_campaign(conn, "c", "c", cfg)
    store.add_tool(conn, "c", "ToolX", "md", None)
    r = import_tool(settings, conn, "c", "ToolX")
    assert r.new == 1 and r.collisions == 1
    assert conn.execute("SELECT COUNT(*) FROM fingerprint_collision WHERE status='open'").fetchone()[0] == 1


def test_fingerprint_identity_without_native_id(settings, conn, tmp_path):
    from paladin import store

    md = tmp_path / "noid.md"
    md.write_text("| Check | Location |\n|---|---|\n| weak-hash | a.py:3 |\n", encoding="utf-8")
    cfg = {
        "id": "c2",
        "target_workbook": "none.xlsx",
        "tools": [
            {
                "label": "ToolY",
                "kind": "md",
                "sheet_name": None,
                "sources": [
                    {
                        "role": "findings",
                        "kind": "md",
                        "path": str(md),
                        "profile": "table-v1",
                        "mapping": {
                            "fields": {
                                "category": {"source": "Check"},
                                "full_filename": {"source": "Location", "transform": "location_path"},
                                "line_number": {"source": "Location", "transform": "location_line"},
                            }
                        },
                    }
                ],
            }
        ],
    }
    store.create_campaign(conn, "c2", "c2", cfg)
    store.add_tool(conn, "c2", "ToolY", "md", None)
    import_tool(settings, conn, "c2", "ToolY")
    import_tool(settings, conn, "c2", "ToolY")
    rows = conn.execute("SELECT source_id, source_id_kind FROM finding WHERE campaign_id='c2'").fetchall()
    assert len(rows) == 1 and rows[0]["source_id"].startswith("fp:") and rows[0]["source_id_kind"] == "fingerprint"


def test_unvalidated_source_is_blocked_with_persisted_proposal(demo):
    r = demo["reports"]["ToolC"]
    assert r.blocked and r.new == 0
    assert (
        demo["conn"].execute("SELECT status FROM input_profile WHERE id = ?", (r.blocked["profile_id"],)).fetchone()[0]
        == "proposed"
    )


def test_prompt_injection_in_md_is_inert_data(demo):
    from paladin.importers import profiles

    conn, settings = demo["conn"], demo["settings"]
    profiles.validate(conn, demo["reports"]["ToolC"].blocked["profile_id"])
    r = import_tool(settings, conn, "demo", "ToolC")
    assert r.new == 5 and r.completeness == "partial"
    c3 = finding_by_source(conn, "C-03")
    assert "ignore all previous instructions" in json.loads(c3["details_json"])["description"]
    assert c3["review_state"] == ReviewState.TO_REVIEW and c3["current_decision_id"] is None
    assert conn.execute("SELECT COUNT(*) FROM decision_event").fetchone()[0] == 0


def test_path_normalization_keeps_dot_directories_and_case():
    from paladin.importers.pipeline import normalized_path

    repos = [{"id": "r1", "name": "shop-api", "scanner_roots": ["C:\\build\\shop-api\\"]}]
    assert normalized_path("C:\\build\\shop-api\\App\\Orders.py", repos) == ("shop-api/App/Orders.py", "r1")
    assert normalized_path("./.github/workflows/ci.yml", repos) == (".github/workflows/ci.yml", None)
    assert normalized_path("./shop-api/app/x.py", repos) == ("shop-api/app/x.py", "r1")
