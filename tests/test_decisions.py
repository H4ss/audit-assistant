import pytest

from paladin.contracts import DISCUSSION_COMMENT, ExportState, ReviewState
from paladin.review import decisions as d
from paladin.store import ConflictError
from tests.conftest import finding_by_source

FID = "FFFFFFFFFFFFFFFFFFFFFFFF00900001"


def _f(conn, sid=FID):
    return finding_by_source(conn, sid)


@pytest.mark.parametrize("verdict", ["TRUE_POSITIVE", "NOT_AN_ISSUE"])
def test_discussion_comment_kept_with_either_verdict(demo, verdict):
    conn = demo["conn"]
    f = _f(conn)
    ev = d.record_decision(conn, f["id"], expected_revision=f["revision"], action="accept", author="me",
                           verdict=verdict, comment=DISCUSSION_COMMENT)
    after = _f(conn)
    assert ev["verdict"] == verdict and ev["comment"] == DISCUSSION_COMMENT
    assert after["discussion_required"] == 1 and after["review_state"] == ReviewState.VALIDATED
    assert d.excel_projection(d.current_decision(conn, f["id"]))[1] == DISCUSSION_COMMENT


def test_double_click_or_stale_response_rejected(demo):
    conn = demo["conn"]
    f = _f(conn)
    d.record_decision(conn, f["id"], expected_revision=f["revision"], action="accept", author="me", verdict="TRUE_POSITIVE")
    with pytest.raises(ConflictError):
        d.record_decision(conn, f["id"], expected_revision=f["revision"], action="accept", author="me", verdict="TRUE_POSITIVE")
    assert conn.execute("SELECT COUNT(*) FROM decision_event WHERE finding_id = ?", (f["id"],)).fetchone()[0] == 1


def test_needs_review_is_not_a_final_decision(demo):
    conn = demo["conn"]
    f = _f(conn)
    with pytest.raises(d.DecisionError):
        d.record_decision(conn, f["id"], expected_revision=f["revision"], action="accept", author="me", verdict="NEEDS_REVIEW")


def test_investigation_requires_question_and_reason(demo):
    conn = demo["conn"]
    f = _f(conn)
    with pytest.raises(d.DecisionError):
        d.record_decision(conn, f["id"], expected_revision=f["revision"], action="investigate", author="me")
    d.record_decision(conn, f["id"], expected_revision=f["revision"], action="investigate", author="me",
                      investigation_question="safe_join couvre-t-il les liens symboliques ?", investigation_reason="protection hors repo")
    after = _f(conn)
    assert after["review_state"] == ReviewState.INVESTIGATING
    assert d.excel_projection(d.current_decision(conn, f["id"])) == (None, None)


def test_comment_only_correction_keeps_verdict_and_history(demo):
    conn = demo["conn"]
    f = _f(conn)
    first = d.record_decision(conn, f["id"], expected_revision=f["revision"], action="accept", author="me", verdict="TRUE_POSITIVE")
    f = _f(conn)
    d.record_decision(conn, f["id"], expected_revision=f["revision"], action="correct", author="me",
                      verdict="TRUE_POSITIVE", comment="Concaténation directe du paramètre customer.")
    cur = d.current_decision(conn, f["id"])
    assert cur["verdict"] == "TRUE_POSITIVE" and cur["comment"] == "Concaténation directe du paramètre customer."
    assert cur["previous_event_id"] == first["id"]


def test_undo_creates_event_and_restores_previous(demo):
    conn = demo["conn"]
    f = _f(conn)
    a = d.record_decision(conn, f["id"], expected_revision=f["revision"], action="accept", author="me", verdict="TRUE_POSITIVE")
    f = _f(conn)
    d.record_decision(conn, f["id"], expected_revision=f["revision"], action="correct", author="me", verdict="NOT_AN_ISSUE")
    f = _f(conn)
    d.undo_last(conn, f["id"], expected_revision=f["revision"], author="me")
    assert d.current_decision(conn, f["id"])["id"] == a["id"]
    f = _f(conn)
    d.undo_last(conn, f["id"], expected_revision=f["revision"], author="me")
    after = _f(conn)
    assert after["current_decision_id"] is None and after["review_state"] == ReviewState.TO_REVIEW
    assert len(d.events(conn, f["id"])) == 4  # rien n'est effacé
    with pytest.raises(d.DecisionError):
        d.undo_last(conn, f["id"], expected_revision=after["revision"], author="me")


def test_skip_has_no_effect_on_decision(demo):
    conn = demo["conn"]
    f = _f(conn)
    d.record_decision(conn, f["id"], expected_revision=f["revision"], action="skip", author="me")
    assert _f(conn)["current_decision_id"] is None


def test_batch_authority_is_explicit(demo):
    conn = demo["conn"]
    f = _f(conn)
    with pytest.raises(d.DecisionError):
        d.record_decision(conn, f["id"], expected_revision=f["revision"], action="batch", author="me", verdict="TRUE_POSITIVE")


def test_drafts_survive_and_clear_on_decision(demo):
    conn = demo["conn"]
    f = _f(conn)
    d.save_draft(conn, f["id"], "TRUE_POSITIVE", "brouillon")
    assert d.get_draft(conn, f["id"])["comment"] == "brouillon"
    d.record_decision(conn, f["id"], expected_revision=f["revision"], action="accept", author="me", verdict="TRUE_POSITIVE")
    assert d.get_draft(conn, f["id"]) is None
