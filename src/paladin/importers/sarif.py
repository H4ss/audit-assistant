"""Lecture SARIF 2.1.0 (format standard d'échange de résultats d'analyse statique).

Seuls les champs standards sont lus ; les extensions propres à un outil restent
dans `extra`. Les résultats sans emplacement physique sont conservés.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paladin.contracts import Completeness
from paladin.importers.records import RawRecord, SourceRead, UnrecognizedPart

# Mapping fixe : les champs SARIF sont standardisés.
SARIF_MAPPING: dict[str, Any] = {
    "fields": {
        "source_id": {"source": "id", "transform": "text"},
        "category": {"source": "rule_name", "transform": "text"},
        "primary_rule_id": {"source": "ruleId", "transform": "text"},
        "full_filename": {"source": "uri", "transform": "text"},
        "primary_location": {"source": "uri", "transform": "basename"},
        "line_number": {"source": "startLine", "transform": "int"},
        "criticality_raw": {"source": "level", "transform": "text"},
        "cwe_ids": {"source": "cwe", "transform": "cwe_list"},
        "description": {"source": "message", "transform": "text"},
        "analyzer_type": {"source": "tool", "transform": "text"},
    },
    "constants": {},
    "comments_from": [],
}


SARIF_FIELDS = ["id", "ruleId", "rule_name", "uri", "startLine", "level", "cwe", "message", "tool"]


def _cwe_from_rule(rule: dict[str, Any]) -> list[str]:
    out = []
    for tag in (rule.get("properties") or {}).get("tags", []) or []:
        t = str(tag).lower()
        if "cwe" in t:
            digits = "".join(ch for ch in t.rsplit("cwe", 1)[-1] if ch.isdigit())
            if digits:
                out.append(f"CWE-{int(digits)}")
    return out


def read_sarif(path: Path) -> SourceRead:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    records: list[RawRecord] = []
    unrecognized: list[UnrecognizedPart] = []
    for run_idx, run in enumerate(doc.get("runs", [])):
        driver = (run.get("tool") or {}).get("driver") or {}
        rules = {r.get("id"): r for r in driver.get("rules", []) or []}
        for res_idx, res in enumerate(run.get("results", []) or []):
            locator = f"{path.name}#runs[{run_idx}].results[{res_idx}]"
            rule = rules.get(res.get("ruleId"), {})
            loc = ((res.get("locations") or [{}])[0] or {}).get("physicalLocation") or {}
            region = loc.get("region") or {}
            fid = res.get("guid") or (res.get("fingerprints") or {}).get("primary")
            if not fid:
                pf = res.get("partialFingerprints") or {}
                fid = next(iter(pf.values()), None) if pf else None
            level = res.get("level") or ((rule.get("defaultConfiguration") or {}).get("level"))
            sec = (rule.get("properties") or {}).get("security-severity")
            fields = {
                "id": fid,
                "ruleId": res.get("ruleId"),
                "rule_name": rule.get("name") or (rule.get("shortDescription") or {}).get("text") or res.get("ruleId"),
                "uri": (loc.get("artifactLocation") or {}).get("uri"),
                "startLine": region.get("startLine"),
                "level": f"{level} (security-severity {sec})" if sec and level else (level or sec),
                "cwe": _cwe_from_rule(rule),
                "message": (res.get("message") or {}).get("text"),
                "tool": driver.get("name"),
            }
            if not fields["ruleId"]:
                unrecognized.append(UnrecognizedPart(locator, "résultat sans ruleId", str(res)[:200]))
                continue
            records.append(RawRecord(fields=fields, locator=locator))
    read = SourceRead(kind="sarif", records=records, field_names=SARIF_FIELDS, unrecognized=unrecognized)
    read.completeness = Completeness.PARTIAL if unrecognized else Completeness.COMPLETE
    return read
