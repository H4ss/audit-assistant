"""Mémoire, règles, groupes et lots (sections 11, 12 et 17)."""

import re

import pytest
from fastapi.testclient import TestClient
from tests.conftest import finding_by_source

from paladin import groups, rules
from paladin.agent.context import build_context
from paladin.contracts import DISCUSSION_COMMENT
from paladin.demo import add_simulated_proposals
from paladin.review import decisions as d
from paladin.review import memory
from paladin.web.app import create_app

F = "FFFFFFFFFFFFFFFFFFFFFFFF00"


@pytest.fixture()
def mem(demo):
    add_simulated_proposals(demo["conn"])
    return demo


def decide(conn, sid, verdict="NOT_AN_ISSUE", comment=None, action="accept", **kw):
    f = finding_by_source(conn, sid)
    return d.record_decision(
        conn,
        f["id"],
        expected_revision=f["revision"],
        action=action,
        author="me",
        verdict=verdict,
        comment=comment,
        **kw,
    )


def sqli_rule(conn):
    """Règle depuis F900002 (requête paramétrée → Not an issue), conditionnée sur la règle SQLi Fortify."""
    decide(conn, F + "900002", "NOT_AN_ISSUE")
    f = finding_by_source(conn, F + "900002")
    rule = rules.create_from_decision(
        conn,
        f["id"],
        title="SQLi sûre",
        author="me",
        conditions={"tool": "Fortify", "primary_rule_id": f["primary_rule_id"]},
    )
    return rules.validate(conn, rule.id, "me")


# ----------------------------------------------------------------- règles


def test_rule_needs_a_final_decision_and_a_real_condition(mem):
    conn = mem["conn"]
    f = finding_by_source(conn, F + "900006")
    with pytest.raises(rules.RuleError):
        rules.create_from_decision(conn, f["id"], title="x", author="me")
    d.record_decision(
        conn,
        f["id"],
        expected_revision=f["revision"],
        action="investigate",
        author="me",
        investigation_question="q ?",
        investigation_reason="r",
    )
    with pytest.raises(rules.RuleError):
        rules.create_from_decision(conn, f["id"], title="x", author="me")
    decide(conn, F + "900005")
    f5 = finding_by_source(conn, F + "900005")
    with pytest.raises(rules.RuleError):
        rules.create_from_decision(conn, f5["id"], title="x", author="me", conditions={"tool": "Fortify"})


def test_rule_is_proposed_then_active_and_shows_where_it_applies(mem):
    conn = mem["conn"]
    decide(conn, F + "900002", "NOT_AN_ISSUE")
    f = finding_by_source(conn, F + "900002")
    rule = rules.create_from_decision(
        conn,
        f["id"],
        title="SQLi sûre",
        author="me",
        conditions={"tool": "Fortify", "primary_rule_id": f["primary_rule_id"]},
        exceptions=[F + "900001"],
    )
    target = finding_by_source(conn, F + "900003")
    assert rules.applicable(conn, target, "Fortify") == []  # proposée : sans effet
    rules.validate(conn, rule.id, "me")
    assert [r.id for r in rules.applicable(conn, target, "Fortify")] == [rule.id]
    assert rules.matches(rules.get(conn, rule.id), finding_by_source(conn, F + "900001"), "Fortify")[0] is False
    # l'agent voit la règle, sans jamais pouvoir l'appliquer lui-même
    ctx = build_context(conn, {"id": "job-test", "finding_id": target["id"], "input_revision": target["revision"]})
    assert ctx["rules"][0]["rule_id"] == rule.id and "vérifier" in ctx["rules"][0]["note"]


def test_revoking_a_rule_puts_derived_decisions_in_reexam(mem):
    conn = mem["conn"]
    rule = sqli_rule(conn)
    g = groups.find(conn, "demo", f"rule:{rule.id}")
    eligible = {m.finding_id: m.revision for m in g.eligible}
    groups.execute(conn, "demo", g.key, eligible, verdict="NOT_AN_ISSUE", comment=None, author="me")
    assert rules.revoke(conn, rule.id, "me", "trop large") == len(eligible)
    for fid in eligible:
        row = conn.execute("SELECT review_state, current_decision_id FROM finding WHERE id = ?", (fid,)).fetchone()
        assert row["review_state"] == "reexam_required" and row["current_decision_id"]  # historique conservé


# ----------------------------------------------------------------- groupes et lots


def test_group_members_are_compared_one_by_one(mem):
    conn = mem["conn"]
    rule = sqli_rule(conn)
    g = groups.find(conn, "demo", f"rule:{rule.id}")
    status = {m.source_id[-6:]: (m.eligible, m.reason) for m in g.members}
    assert status["900001"] == (False, "proposition différente (TRUE_POSITIVE)")  # cas différent : exclu
    assert status["900002"] == (False, "déjà décidé")
    assert status["900003"] == (True, None)
    sink = next(x for x in groups.groups(conn, "demo") if x.kind == "root_cause")
    reasons = {m.source_id[-6:]: m.reason for m in sink.members}
    assert reasons == {
        "900010": "références de code invalides dans la proposition",
        "900011": "aucune proposition individuelle : analyser ce membre d'abord",
    }


def test_batch_records_one_decision_per_member_and_is_undoable(mem):
    conn = mem["conn"]
    rule = sqli_rule(conn)
    g = groups.find(conn, "demo", f"rule:{rule.id}")
    frozen = {m.finding_id: m.revision for m in g.eligible}
    batch_id = groups.execute(
        conn, "demo", g.key, frozen, verdict="NOT_AN_ISSUE", comment=DISCUSSION_COMMENT, author="me"
    )
    f3 = finding_by_source(conn, F + "900003")
    ev = d.current_decision(conn, f3["id"])
    assert (ev["action"], ev["authority"], ev["batch_id"], ev["rule_id"], ev["rule_version"]) == (
        "batch",
        "batch",
        batch_id,
        rule.id,
        1,
    )
    assert ev["comment"] == DISCUSSION_COMMENT and ev["analysis_id"]
    report = groups.undo(conn, batch_id, "me")
    assert report["annulés"] == [F + "900003"]
    assert finding_by_source(conn, F + "900003")["current_decision_id"] is None
    with pytest.raises(groups.BatchError):
        groups.undo(conn, batch_id, "me")


def test_frozen_list_shared_comment_and_rule_verdict_are_enforced(mem):
    conn = mem["conn"]
    rule = sqli_rule(conn)
    g = groups.find(conn, "demo", f"rule:{rule.id}")
    frozen = {m.finding_id: m.revision for m in g.eligible}
    with pytest.raises(groups.BatchError, match="ligne"):
        groups.execute(conn, "demo", g.key, frozen, verdict="NOT_AN_ISSUE", comment="voir products.py:17", author="me")
    with pytest.raises(groups.BatchError, match="règle"):
        groups.execute(conn, "demo", g.key, frozen, verdict="TRUE_POSITIVE", comment=None, author="me")
    stale = {fid: rev - 1 for fid, rev in frozen.items()}
    with pytest.raises(groups.BatchError, match="liste a changé"):
        groups.execute(conn, "demo", g.key, stale, verdict="NOT_AN_ISSUE", comment=None, author="me")
    other = finding_by_source(conn, F + "900001")
    with pytest.raises(groups.BatchError, match="liste a changé"):
        groups.execute(
            conn, "demo", g.key, {other["id"]: other["revision"]}, verdict="NOT_AN_ISSUE", comment=None, author="me"
        )


def test_undo_batch_spares_members_changed_since(mem):
    conn = mem["conn"]
    rule = sqli_rule(conn)
    g = groups.find(conn, "demo", f"rule:{rule.id}")
    frozen = {m.finding_id: m.revision for m in g.eligible}
    batch_id = groups.execute(conn, "demo", g.key, frozen, verdict="NOT_AN_ISSUE", comment=None, author="me")
    decide(conn, F + "900003", "NOT_AN_ISSUE", comment="revu à la main", action="correct")
    report = groups.undo(conn, batch_id, "me")
    assert report["non touchés (modifiés depuis)"] == [F + "900003"]
    assert d.current_decision(conn, finding_by_source(conn, F + "900003")["id"])["comment"] == "revu à la main"


# ----------------------------------------------------------------- mémoire et mesures


def test_precedents_flag_contradictions_and_hide_reference_from_agent(mem):
    conn = mem["conn"]
    decide(conn, F + "900002", "NOT_AN_ISSUE")
    decide(conn, F + "900003", "TRUE_POSITIVE", action="correct")
    target = finding_by_source(conn, F + "900001")
    prec = memory.precedents(conn, target)
    assert prec["contradiction"] and {p["basis"] for p in prec["items"]} == {"même règle"}
    conn.execute("UPDATE finding SET is_reference = 1 WHERE source_id = ?", (F + "900003",))
    ctx = build_context(conn, {"id": "job-test", "finding_id": target["id"], "input_revision": target["revision"]})
    assert [p["source_id"] for p in ctx["precedents"]] == [F + "900002"]  # référence jamais montrée à l'agent


def test_pilot_metrics_count_dangerous_errors(mem):
    conn = mem["conn"]
    decide(conn, F + "900002", "TRUE_POSITIVE", action="correct", correction_category="protection")  # proposé NAI
    decide(conn, F + "900001", "TRUE_POSITIVE", comment="Concaténation", action="correct")  # commentaire seul
    decide(conn, F + "900004", "TRUE_POSITIVE")  # acceptée
    m = memory.pilot_metrics(conn, "demo")
    assert m["missed_tp"] == [F + "900002"] and m["comment_only"] == 1 and m["accepted"] == 1
    assert m["categories"] == {"protection manquée": 1} and m["proposals_simulated"] == m["proposals"]
    assert m["bad_references"] >= 1 and m["abstentions"] == 1


# ----------------------------------------------------------------- pages


def test_rule_group_and_stats_pages(mem):
    conn, settings = mem["conn"], mem["settings"]
    c, t = TestClient(create_app(settings), base_url="http://127.0.0.1:8765"), settings.ui_token()
    decide(conn, F + "900002", "NOT_AN_ISSUE")
    f2 = finding_by_source(conn, F + "900002")
    assert "Créer une règle à partir de cette décision" in c.get(f"/c/demo/f/{f2['id']}?view=all").text
    assert "Nouvelle règle à partir de" in c.get(f"/c/demo/rules?finding={f2['id']}").text
    r = c.post(
        "/c/demo/rules/create",
        data={
            "token": t,
            "finding_id": f2["id"],
            "title": "SQLi sûre",
            "cond_tool": "Fortify",
            "cond_primary_rule_id": f2["primary_rule_id"],
            "app_scope": "1",
        },
    )
    assert "proposée" in r.text
    rid = re.search(r"/c/demo/rules/([0-9a-f]{32})/validate", r.text).group(1)
    assert "active" in c.post(f"/c/demo/rules/{rid}/validate", data={"token": t}).text
    f3 = finding_by_source(conn, F + "900003")
    assert "Règle applicable" in c.get(f"/c/demo/f/{f3['id']}?view=all").text
    gpage = c.get("/c/demo/groups", params={"key": f"rule:{rid}"}).text
    assert "exclu : proposition différente" in gpage
    rev = re.search(rf'name="rev_{f3["id"]}" value="(\d+)"', gpage).group(1)
    r = c.post(
        "/c/demo/groups/batch",
        data={
            "token": t,
            "key": f"rule:{rid}",
            "member": [f3["id"]],
            f"rev_{f3['id']}": rev,
            "verdict": "NOT_AN_ISSUE",
            "comment": "",
        },
    )
    assert "1 décision(s) enregistrée(s), une par membre" in r.text
    stats = c.get("/c/demo/stats", params={"search": "SQL"}).text
    assert "Vrais problèmes proposés" in stats and "décision(s) finales" in stats
