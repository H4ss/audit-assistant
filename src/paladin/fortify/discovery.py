"""Découverte SSC : applications regroupées par préfixe, version `release` et nombre de findings.

Règle de regroupement (configurable) : `APP.SUBAPP1` et `APP.SUBAPP2` forment UNE
entrée (groupe `APP`) ; `APP2.SUBAPP1` forme une autre entrée. Une application sans
séparateur forme son propre groupe.

Pour chaque sous-application, la version nommée exactement `release` est
recherchée : absente ou ambiguë, la sous-application est signalée et n'est jamais
remplacée par une autre version.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from paladin.importers.fortify import FortifyError

STATUS_OK = "ok"
STATUS_ABSENT = "release absente"
STATUS_AMBIGUOUS = "release ambiguë"


@dataclass
class SubApp:
    app_id: Any
    app_name: str
    status: str
    version_id: Any = None
    version_name: str | None = None
    issue_count: int | None = None
    other_versions: list[str] = field(default_factory=list)
    release_ids: list[Any] = field(default_factory=list)


@dataclass
class Group:
    key: str
    apps: list[SubApp]

    @property
    def total_findings(self) -> int:
        return sum(a.issue_count or 0 for a in self.apps if a.status == STATUS_OK)

    @property
    def ready(self) -> list[SubApp]:
        return [a for a in self.apps if a.status == STATUS_OK]

    @property
    def blocked(self) -> list[SubApp]:
        return [a for a in self.apps if a.status != STATUS_OK]

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "total_findings": self.total_findings, "apps": [asdict(a) for a in self.apps]}


def group_key(name: str, separator: str = ".") -> str:
    return name.split(separator, 1)[0] if separator and separator in name else name


def discover(
    client: Any,
    version_name: str = "release",
    separator: str = ".",
    count: bool = True,
    name_filter: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[Group]:
    """Inventaire en lecture seule. `name_filter` restreint aux applications contenant ce texte."""
    apps = sorted(client.list_applications().data, key=lambda a: str(a.get("name")))
    if name_filter:
        apps = [a for a in apps if name_filter.lower() in str(a.get("name", "")).lower()]
    groups: dict[str, list[SubApp]] = {}
    for i, app in enumerate(apps, start=1):
        name = str(app.get("name"))
        if progress:
            progress(f"{i}/{len(apps)} {name}")
        try:
            versions = client.list_versions(app["id"]).data
        except FortifyError as exc:
            groups.setdefault(group_key(name, separator), []).append(
                SubApp(app["id"], name, f"erreur : {exc}", other_versions=[])
            )
            continue
        releases = [v for v in versions if v.get("name") == version_name]
        others = sorted(str(v.get("name")) for v in versions if v.get("name") != version_name)
        if len(releases) == 1:
            v = releases[0]
            sub = SubApp(app["id"], name, STATUS_OK, v["id"], v["name"], other_versions=others, release_ids=[v["id"]])
            if count:
                sub.issue_count = client.issue_count(v["id"])
        elif not releases:
            sub = SubApp(app["id"], name, STATUS_ABSENT, other_versions=others)
        else:
            sub = SubApp(
                app["id"], name, STATUS_AMBIGUOUS, other_versions=others, release_ids=[v["id"] for v in releases]
            )
        groups.setdefault(group_key(name, separator), []).append(sub)
    return [Group(k, sorted(v, key=lambda a: a.app_name)) for k, v in sorted(groups.items())]


def campaign_slug(key: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9_-]+", "-", key.lower()).strip("-")
    return (slug or "ssc")[:40] if len(slug) >= 2 else f"ssc-{slug or 'app'}"
