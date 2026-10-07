"""SSC FICTIF (transport HTTP simulé) pour la démo et les tests.

Reproduit la forme de l'API SSC v1 utilisée par `ssc.SSCClient`, à partir de
`fixtures/demo/fortify/ssc_catalog.json`. N'atteste en rien du comportement
d'une instance réelle : c'est le rôle de `paladin fortify check`.
"""

from __future__ import annotations

import base64
import json
import re
from functools import cache
from typing import Any

import httpx

from paladin.demo import fixtures_root

DEMO_TOKEN = "demo-token"  # noqa: S105 — jeton factice du SSC de démonstration
_ACCEPTED = "FortifyToken " + base64.b64encode(DEMO_TOKEN.encode()).decode()


@cache
def _catalog() -> dict[str, Any]:
    return json.loads((fixtures_root() / "fortify" / "ssc_catalog.json").read_text(encoding="utf-8"))


def _fixture_issues(version_id: int) -> tuple[list[dict[str, Any]], int]:
    root = fixtures_root() / "fortify"
    items: list[dict[str, Any]] = []
    count = 0
    for page in sorted(root.glob(f"issues_{version_id}_p*.json")):
        doc = json.loads(page.read_text(encoding="utf-8"))
        items += doc["data"]
        count = doc.get("count", count)
    return items, count


def _generated(version_id: int, spec: str, app: str) -> list[dict[str, Any]]:
    _, n, path = spec.split(":", 2)
    out = []
    for i in range(1, int(n) + 1):
        iid = version_id * 1000 + i
        out.append(
            {
                "id": iid,
                "issueInstanceId": f"{iid:032X}",
                "issueName": "Log Forging" if i % 2 else "SQL Injection",
                "kingdom": "Input Validation and Representation",
                "friority": "Medium" if i % 2 else "High",
                "primaryLocation": path.rsplit("/", 1)[-1],
                "lineNumber": 10 + i,
                "fullFileName": f"/build/{app}/{path}",
                "analyzer": "dataflow",
                "primaryRuleGuid": f"RULE-{i % 3}",
                "projectVersionId": version_id,
                "projectName": app,
                "projectVersionName": "release",
            }
        )
    return out


def _issues(version: dict[str, Any], app: str) -> tuple[list[dict[str, Any]], int]:
    spec = version["issues"]
    if spec.startswith("fixture:"):
        return _fixture_issues(int(spec.split(":")[1]))
    items = _generated(version["id"], spec, app)
    return items, len(items)


def _page(items: list[dict[str, Any]], params: httpx.QueryParams, count: int | None = None) -> dict[str, Any]:
    start, limit = int(params.get("start", 0)), int(params.get("limit", 200))
    return {"data": items[start : start + limit], "count": len(items) if count is None else count, "responseCode": 200}


def handler(request: httpx.Request, *, fail_once: set[str] | None = None) -> httpx.Response:
    if request.headers.get("authorization") != _ACCEPTED:
        return httpx.Response(401, json={"message": "Unauthorized", "responseCode": 401})
    path = request.url.path
    if fail_once is not None and path in fail_once:
        fail_once.discard(path)
        return httpx.Response(502, text="Bad Gateway")
    apps = _catalog()["applications"]
    if m := re.fullmatch(r"/ssc/api/v1/projects", path):
        return httpx.Response(200, json=_page([{"id": a["id"], "name": a["name"]} for a in apps], request.url.params))
    if m := re.fullmatch(r"/ssc/api/v1/projects/(\d+)/versions", path):
        app = next((a for a in apps if a["id"] == int(m.group(1))), None)
        if app is None:
            return httpx.Response(404, json={"message": "Not found"})
        versions = [
            {"id": v["id"], "name": v["name"], "project": {"id": app["id"], "name": app["name"]}}
            for v in app["versions"]
        ]
        return httpx.Response(200, json=_page(versions, request.url.params))
    if m := re.fullmatch(r"/ssc/api/v1/projectVersions/(\d+)/issues", path):
        vid = int(m.group(1))
        for app in apps:
            for v in app["versions"]:
                if v["id"] == vid:
                    items, count = _issues(v, app["name"])
                    return httpx.Response(200, json=_page(items, request.url.params, count))
        return httpx.Response(404, json={"message": "Not found"})
    if m := re.fullmatch(r"/ssc/api/v1/issueDetails/(\d+)", path):
        fixture = fixtures_root() / "fortify" / "details" / f"{m.group(1)}.json"
        if fixture.exists():
            return httpx.Response(200, content=fixture.read_bytes(), headers={"content-type": "application/json"})
        return httpx.Response(200, json={"data": {"id": int(m.group(1)), "brief": "Synthetic.", "traceNodes": None}})
    return httpx.Response(404, json={"message": "Not found"})


def demo_transport(fail_once: set[str] | None = None) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: handler(request, fail_once=fail_once))
