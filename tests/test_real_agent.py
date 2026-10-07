"""Test d'intégration RÉEL (opt-in, payant, exclu de la CI) : OpenCode + modèle configuré.

Lancer : PALADIN_REAL=1 OPENROUTER_API_KEY=... python -m pytest -m real tests/test_real_agent.py -s
Coût attendu : environ 0,05 à 0,10 $ (un job, modèle openrouter/z-ai/glm-5.3).
"""

import os
import shutil

import pytest
from tests.conftest import finding_by_source

from paladin.agent import jobs, runner

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(os.environ.get("PALADIN_REAL") != "1", reason="intégration réelle opt-in : PALADIN_REAL=1"),
]


def test_real_opencode_agent_submits_a_verified_proposal(demo):
    if not shutil.which("opencode") or not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OpenCode ou OPENROUTER_API_KEY absent")
    conn = demo["conn"]
    jobs.enqueue_analysis(conn, "demo", [finding_by_source(conn, "FFFFFFFFFFFFFFFFFFFFFFFF00900011")["id"]])
    report = runner.run_agent(demo["settings"], conn, "demo", max_jobs=1, budget_usd=0.5, job_timeout=600)
    print(report)
    assert report.outcomes[0].status == "proposition reçue", report.outcomes[0].detail
    analysis = conn.execute("SELECT * FROM analysis WHERE is_simulated = 0").fetchone()
    assert analysis["model_requested"].startswith("openrouter/")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE analysis_id = ? AND reference_check = 'verified'", (analysis["id"],)
        ).fetchone()[0]
        >= 1
    )
    assert conn.execute("SELECT COUNT(*) FROM decision_event").fetchone()[0] == 0  # une proposition, pas une décision
