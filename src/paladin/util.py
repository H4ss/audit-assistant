"""Petits utilitaires partagés (horodatage, identifiants, empreintes)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def new_id() -> str:
    return uuid.uuid4().hex


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def dumps(value: Any) -> str:
    """JSON stable (clés triées) pour stockage et empreintes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads(text: str | None, default: Any = None) -> Any:
    return default if text is None else json.loads(text)


def fingerprint(*parts: Any) -> str:
    return sha256_bytes(dumps(list(parts)).encode("utf-8"))
