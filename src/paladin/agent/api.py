"""API de l'agent (autorité « agent ») : réclamer, lire le contexte, proposer.

Cette API n'expose aucune opération de décision, de règle ou d'écriture Excel :
l'agent propose, seul l'analyste valide (jeton d'interface distinct).
"""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from paladin.agent import jobs
from paladin.agent.context import ContextError, build_context, read_code, search_code
from paladin.analysis import ProposalRejectedError, store_proposal
from paladin.contracts import AgentProposal

MAX_VALIDATION_ERRORS = 3


def _errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors()][:20]


def build_router(conn: sqlite3.Connection, agent_token: str, skill_version: str | None) -> APIRouter:
    router = APIRouter(prefix="/api/agent")

    def auth(authorization: str | None) -> None:
        expected = f"Bearer {agent_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(401, "Jeton d'agent invalide.")

    def lease(job_id: str, token: str | None) -> dict[str, Any]:
        try:
            return jobs.check_lease(conn, job_id, token or "")
        except jobs.JobError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @router.post("/claim")
    async def claim(request: Request, authorization: str | None = Header(None)):
        auth(authorization)
        body = await request.json() if await request.body() else {}
        worker = str(body.get("worker") or "opencode")[:80]
        job = jobs.claim(conn, worker, body.get("campaign_id"), model_requested=body.get("model_requested"))
        if job is None:
            return Response(status_code=204)
        return {
            "job_id": job["id"],
            "lease_token": job["lease_token"],
            "lease_expires_at": job["lease_expires_at"],
            "finding_id": job["finding_id"],
            "input_revision": job["input_revision"],
            "attempt": job["attempt"],
        }

    @router.get("/jobs/{job_id}/context")
    def context(job_id: str, authorization: str | None = Header(None), x_lease_token: str | None = Header(None)):
        auth(authorization)
        job = lease(job_id, x_lease_token)
        return build_context(conn, job)

    @router.get("/jobs/{job_id}/code")
    def code(
        job_id: str,
        repo: str,
        path: str,
        start: int = 1,
        end: int | None = None,
        authorization: str | None = Header(None),
        x_lease_token: str | None = Header(None),
    ):
        auth(authorization)
        job = lease(job_id, x_lease_token)
        try:
            return read_code(conn, job["campaign_id"], repo, path, start, end)
        except ContextError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.get("/jobs/{job_id}/search")
    def search(
        job_id: str,
        repo: str,
        pattern: str,
        glob: str | None = None,
        regex: bool = False,
        authorization: str | None = Header(None),
        x_lease_token: str | None = Header(None),
    ):
        auth(authorization)
        job = lease(job_id, x_lease_token)
        try:
            return search_code(conn, job["campaign_id"], repo, pattern, glob, regex)
        except ContextError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.post("/jobs/{job_id}/heartbeat")
    def heartbeat(job_id: str, authorization: str | None = Header(None), x_lease_token: str | None = Header(None)):
        auth(authorization)
        try:
            return {"lease_expires_at": jobs.heartbeat(conn, job_id, x_lease_token or "")}
        except jobs.JobError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @router.post("/jobs/{job_id}/proposal")
    async def proposal(
        job_id: str,
        request: Request,
        authorization: str | None = Header(None),
        x_lease_token: str | None = Header(None),
    ):
        auth(authorization)
        job = lease(job_id, x_lease_token)
        body = await request.json()
        meta = body.pop("_meta", {}) if isinstance(body, dict) else {}
        try:
            parsed = AgentProposal.model_validate(body)
        except ValidationError as exc:
            jobs.record_validation_error(conn, job_id)
            remaining = MAX_VALIDATION_ERRORS - job["validation_errors"] - 1
            if remaining <= 0:
                jobs.fail(
                    conn,
                    job_id,
                    x_lease_token or "",
                    "réponses non conformes au schéma : " + "; ".join(_errors(exc)[:3]),
                )
                return JSONResponse(
                    status_code=422, content={"error": "Trop de réponses non conformes : job abandonné."}
                )
            return JSONResponse(
                status_code=422,
                content={
                    "error": "Réponse non conforme au schéma : corriger puis soumettre à nouveau.",
                    "details": _errors(exc),
                    "remaining_attempts": remaining,
                },
            )
        if parsed.finding_id != job["finding_id"]:
            return JSONResponse(status_code=422, content={"error": "finding_id ne correspond pas au job réclamé."})
        try:
            analysis = store_proposal(
                conn,
                job["finding_id"],
                parsed,
                job_id=job_id,
                model_requested=meta.get("model_requested") or job["model_requested"],
                model_provider=meta.get("model_provider"),
                model_resolved=meta.get("model_resolved"),
                skill_version=skill_version,
                context_version=meta.get("context_version"),
                is_blind=bool(job["blind"]),
                conventions_version=job["conventions_version"],
            )
        except ProposalRejectedError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        jobs.complete(conn, job_id)
        refs = analysis["validation"]["references"]
        return {
            "status": "enregistrée (proposition, pas une décision)",
            "analysis_id": analysis["id"],
            "references": refs,
            "warning": None
            if all(r["status"] == "verified" for r in refs)
            else "Certaines références ne correspondent pas au code : elles seront signalées à l'analyste.",
        }

    @router.post("/jobs/{job_id}/fail")
    async def fail(
        job_id: str,
        request: Request,
        authorization: str | None = Header(None),
        x_lease_token: str | None = Header(None),
    ):
        auth(authorization)
        body = await request.json()
        try:
            job = jobs.fail(conn, job_id, x_lease_token or "", str(body.get("reason") or "sans motif"))
        except jobs.JobError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        return {"status": job["status"], "attempt": job["attempt"]}

    return router
