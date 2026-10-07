"""Faux `opencode run` pour les tests : se comporte comme l'agent via l'API Paladin réelle.

Lit .paladin/connection.json dans le dossier courant (comme les outils TypeScript),
réclame un job, lit le contexte, soumet une proposition fondée sur l'extrait de code,
puis émet un événement JSON de fin d'étape avec un coût fictif.
Variables : FAKE_OPENCODE_MODE = ok | silent | invalid.
"""

import json
import os
import sys
from pathlib import Path

import httpx

if not sys.stdin.isatty() and sys.stdin.read() is None:  # comme opencode : lit stdin jusqu'à EOF
    sys.exit(3)
if os.environ.get("PWD") and Path(os.environ["PWD"]).resolve() != Path.cwd().resolve():
    # comme opencode : le projet est cherché dans $PWD
    print(json.dumps({"type": "error", "error": {"message": 'Agent not found: "paladin-analyst"'}}))
    sys.exit(1)
mode = os.environ.get("FAKE_OPENCODE_MODE", "ok")
if mode in ("probe_ok", "probe_bad"):  # sondage des accès : trace d'outils simulée
    tools = [("paladin_claim", "completed"), ("bash", "error")]
    if mode == "probe_bad":
        tools.append(("bash", "completed"))
    for name, status in tools:
        print(json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": name, "state": {"status": status}}}))
    sys.exit(0)
conn = json.loads(Path(".paladin/connection.json").read_text(encoding="utf-8"))
headers = {"Authorization": f"Bearer {conn['token']}"}
mode = os.environ.get("FAKE_OPENCODE_MODE", "ok")
base = conn["url"]

r = httpx.post(
    f"{base}/api/agent/claim",
    json={"worker": conn["worker"], "campaign_id": conn["campaign_id"]},
    headers=headers,
    timeout=10,
)
if r.status_code == 204:
    print(json.dumps({"type": "text", "text": "Aucun job"}))
    sys.exit(0)
job = r.json()
lease = {**headers, "X-Lease-Token": job["lease_token"]}
ctx = httpx.get(f"{base}/api/agent/jobs/{job['job_id']}/context", headers=lease, timeout=10).json()
if mode == "silent":
    sys.exit(0)  # session terminée sans proposition
excerpt = ctx["code_excerpt"]
line = excerpt["focus_line"] or excerpt["lines"][0]["n"]
text = next(x["text"] for x in excerpt["lines"] if x["n"] == line)
proposal = {
    "finding_id": job["finding_id"],
    "input_revision": job["input_revision"],
    "proposed_verdict": "NEEDS_REVIEW" if mode == "ok" else "MAYBE",
    "summary": "Proposition de test (faux opencode).",
    "evidence": [{"file": f"{excerpt['repo']}/{excerpt['path']}", "line_start": line, "excerpt": text.strip()}],
    "missing_information": ["test"],
    "model_confidence": {"level": "low", "calibrated": False},
    "next_action": "Rien : test.",
    "_meta": {"model_requested": conn["model_requested"], "model_provider": conn["model_provider"]},
}
res = httpx.post(f"{base}/api/agent/jobs/{job['job_id']}/proposal", json=proposal, headers=lease, timeout=10)
print(json.dumps({"type": "tool", "status": res.status_code, "body": res.json()}))
print(
    json.dumps(
        {"type": "step-finish", "cost": 0.0012, "tokens": {"input": 1000, "output": 200}, "modelID": "z-ai/glm-5.3"}
    )
)
