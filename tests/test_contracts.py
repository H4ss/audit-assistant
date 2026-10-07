import pytest
from pydantic import ValidationError

from paladin import contracts as c

SPEC_EXAMPLE = {
    "finding_id": "demo-001",
    "input_revision": 1,
    "proposed_verdict": "NEEDS_REVIEW",
    "summary": "La protection appelée n'a pas encore été examinée.",
    "suggested_analysis_result_comment": "",
    "discussion_required": False,
    "discussion_reason": "",
    "evidence": [],
    "assumptions": [],
    "missing_information": ["Implémentation de la protection"],
    "checks": [{"name": "protection_effective", "status": "unknown"}],
    "model_confidence": {"level": "low", "calibrated": False},
    "candidate_rule_ids": [],
    "next_action": "Lire la fonction appelée et ses usages pertinents.",
}


def test_excel_result_has_exactly_two_values():
    assert {"True Positive", "Not an issue"} == c.EXCEL_ANALYSIS_RESULT_VALUES
    assert c.verdict_to_excel(c.Verdict.TRUE_POSITIVE) == "True Positive"
    assert c.verdict_to_excel(c.Verdict.NOT_AN_ISSUE) == "Not an issue"
    assert c.verdict_to_excel(c.Verdict.NEEDS_REVIEW) is None
    assert c.verdict_to_excel(None) is None


def test_discussion_comment_is_exact():
    assert c.DISCUSSION_COMMENT == "security appetite to be discussed"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("TP", c.Verdict.TRUE_POSITIVE),
        ("fp", c.Verdict.NOT_AN_ISSUE),
        ("False Positive", c.Verdict.NOT_AN_ISSUE),
        ("Not an issue", c.Verdict.NOT_AN_ISSUE),
        ("true-positive", c.Verdict.TRUE_POSITIVE),
        ("needs_review", c.Verdict.NEEDS_REVIEW),
    ],
)
def test_legacy_verdicts_normalized(raw, expected):
    assert c.normalize_verdict(raw) == expected


def test_unknown_verdict_rejected():
    with pytest.raises(ValueError):
        c.normalize_verdict("probably fine")


def test_default_columns_match_contract():
    headers = [col.header for col in c.DEFAULT_COLUMNS]
    assert headers == [
        "Application name",
        "Version name",
        "Category",
        "Primary location",
        "Line number",
        "Full filename",
        "Criticality",
        "Comments",
        "Analyzer",
        "Primary rule ID",
        "Instance ID",
        "Fortify Category",
        "CWE",
        "analysis result",
        "Analysis result comment",
    ]
    assert {"analyst_result", "analyst_comment"} == c.ANALYST_KEYS
    assert c.found_in_header("ToolB") == "Found in ToolB"
    assert c.criticality_in_header("ToolB") == "criticality in ToolB"


@pytest.mark.parametrize(
    "raw,expected",
    [("79", "CWE-79"), ("CWE-89", "CWE-89"), ("cwe 22", "CWE-22"), ("CWE ID 117", "CWE-117"), ("XSS", None)],
)
def test_cwe_normalization(raw, expected):
    assert c.normalize_cwe(raw) == expected


def test_cwe_list_export_is_stable():
    ids = c.parse_cwe_list("CWE-89, 79;cwe 89")
    assert ids == ["CWE-89", "CWE-79"]
    assert c.format_cwe_ids(ids) == "CWE-79; CWE-89"
    assert c.parse_cwe_list(None) == []


def test_spec_agent_example_validates():
    p = c.AgentProposal.model_validate(SPEC_EXAMPLE)
    assert p.proposed_verdict == c.Verdict.NEEDS_REVIEW
    assert p.discussion_required is False


def test_agent_proposal_rejects_extra_fields_and_calibration_claims():
    with pytest.raises(ValidationError):
        c.AgentProposal.model_validate({**SPEC_EXAMPLE, "validated": True})
    with pytest.raises(ValidationError):
        c.AgentProposal.model_validate({**SPEC_EXAMPLE, "model_confidence": {"level": "high", "calibrated": True}})
    with pytest.raises(ValidationError):
        c.AgentProposal.model_validate({**SPEC_EXAMPLE, "proposed_verdict": "MAYBE"})


def test_agent_proposal_accepts_legacy_tp_label():
    p = c.AgentProposal.model_validate({**SPEC_EXAMPLE, "proposed_verdict": "TP"})
    assert p.proposed_verdict == c.Verdict.TRUE_POSITIVE


def test_normalized_finding_drops_invented_zero_line():
    f = c.NormalizedFinding(tool="X", locator="l1", line_number=0)
    assert f.line_number is None


@pytest.mark.parametrize("name", ["a/b", "x" * 32, "History", "'quoted'", "bad?"])
def test_sheet_name_rules(name):
    with pytest.raises(ValidationError):
        c.SheetSchemaProposal(tool="ToolC", sheet_name=name, columns=[])
