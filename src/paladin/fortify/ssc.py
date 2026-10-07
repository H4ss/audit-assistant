"""Client Fortify SSC (REST v1), en lecture seule.

Endpoints utilisés (forme publique de l'API SSC v1) — **vérifiés sur l'instance
par `paladin fortify check` avant tout import** ; aucun n'est présumé exister :

    GET /api/v1/projects                                 applications
    GET /api/v1/projects/{id}/versions                   versions d'une application
    GET /api/v1/projectVersions/{id}/issues              findings (paginé, champ `count`)
    GET /api/v1/issueDetails/{id}                        détail d'un finding (trace, description)

Authentification : en-tête `Authorization: FortifyToken <jeton>`. Selon la
version de SSC, le jeton est attendu tel qu'affiché ou encodé en base64 : le
client essaie la forme fournie puis l'autre, et retient celle qui fonctionne.
TLS n'est jamais désactivé : un certificat d'entreprise se déclare via `ca_bundle`.
Le proxy suit les variables standard (HTTPS_PROXY, NO_PROXY).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from paladin.config import Settings
from paladin.importers.fortify import FortifyError, Page, PageFailedError, TokenExpiredError

API_PREFIX = "/api/v1"
PAGE_LIMIT = 200
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class EndpointMissingError(FortifyError):
    pass


class ForbiddenError(FortifyError):
    pass


def api_base(url: str) -> str:
    """`https://ssc.corp/ssc` ou `.../ssc/api/v1` -> `https://ssc.corp/ssc/api/v1`."""
    base = url.strip().rstrip("/")
    return base if base.endswith(API_PREFIX) else base + API_PREFIX


def token_variants(token: str) -> list[str]:
    """Forme fournie d'abord, puis l'autre encodage (base64 <-> décodé)."""
    t = token.strip()
    variants = [t]
    try:
        decoded = base64.b64decode(t, validate=True).decode("utf-8")
        if decoded and decoded.isprintable():
            variants.append(decoded)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        variants.append(base64.b64encode(t.encode("utf-8")).decode("ascii"))
    if _UUID_RE.match(t) and len(variants) == 1:
        variants.append(base64.b64encode(t.encode("utf-8")).decode("ascii"))
    return list(dict.fromkeys(variants))


@dataclass
class SSCFilters:
    """Filtres de collecte, enregistrés dans le manifeste (section 5.2)."""

    showhidden: bool = False
    showremoved: bool = False
    showsuppressed: bool = False
    filterset: str | None = None

    def params(self) -> dict[str, str]:
        out = {k: str(getattr(self, k)).lower() for k in ("showhidden", "showremoved", "showsuppressed")}
        if self.filterset:
            out["filterset"] = self.filterset
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            **{k: getattr(self, k) for k in ("showhidden", "showremoved", "showsuppressed")},
            "filterset": self.filterset,
        }


@dataclass
class SSCClient:
    """Source Fortify SSC compatible avec le collecteur (`importers.fortify.collect`)."""

    base_url: str
    token: str
    verify: bool | str = True
    timeout: float = 30.0
    filters: SSCFilters = field(default_factory=SSCFilters)
    transport: httpx.BaseTransport | None = None
    name: str = "ssc"
    calls: list[dict[str, Any]] = field(default_factory=list)  # journal des appels (sans secret)

    def __post_init__(self) -> None:
        self.base = api_base(self.base_url)
        self._variants = token_variants(self.token)
        self._active = 0
        self._http = httpx.Client(timeout=self.timeout, verify=self.verify, transport=self.transport, trust_env=True)

    @property
    def token_form(self) -> str:
        return "telle que fournie" if self._active == 0 else "encodage alternatif"

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ HTTP

    def _get(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, bytes]:
        url = self.base + path
        last_status = None
        for attempt in range(2):  # une nouvelle tentative pour les erreurs serveur ou réseau transitoires
            for idx in range(self._active, len(self._variants)):
                headers = {"Authorization": f"FortifyToken {self._variants[idx]}", "Accept": "application/json"}
                try:
                    r = self._http.get(url, params=params, headers=headers)
                except httpx.ConnectError as exc:
                    raise _network_error(exc, self.base) from None
                except httpx.TimeoutException:
                    if attempt == 0:
                        break
                    raise PageFailedError(0, f"délai dépassé sur {path}") from None
                self.calls.append({"path": path, "status": r.status_code})
                last_status = r.status_code
                if r.status_code == 401:
                    continue  # essayer l'autre encodage du jeton
                self._active = idx
                if r.status_code == 403:
                    raise ForbiddenError(
                        f"Accès refusé à {path}.",
                        "Demander à l'administrateur SSC un accès en lecture à cette application.",
                    )
                if r.status_code == 404:
                    raise EndpointMissingError(
                        f"Endpoint absent ou ressource inconnue : {path}.",
                        "Lancer `Paladin.cmd fortify check` et transmettre le rapport (version de SSC différente ?).",
                    )
                if r.status_code >= 500:
                    if attempt == 0:
                        break
                    raise PageFailedError(0, f"HTTP {r.status_code} sur {path}")
                if r.status_code >= 400:
                    raise FortifyError(f"HTTP {r.status_code} sur {path} : {r.text[:200]}", "Vérifier les paramètres.")
                try:
                    return r.json(), r.content
                except json.JSONDecodeError:
                    raise FortifyError(
                        f"Réponse non JSON sur {path} (page de connexion ou proxy ?).",
                        "Vérifier l'URL SSC (elle se termine en général par /ssc) et le proxy.",
                    ) from None
            if last_status == 401:
                raise TokenExpiredError()
        raise PageFailedError(0, f"échec répété sur {path}")

    def _all(self, path: str, params: dict[str, Any] | None = None) -> Page:
        data: list[dict[str, Any]] = []
        raws: list[bytes] = []
        start = 0
        total = None
        while True:
            doc, raw = self._get(path, {**(params or {}), "start": start, "limit": PAGE_LIMIT})
            items = doc.get("data") or []
            data += items
            raws.append(raw)
            total = doc.get("count", total)
            start += len(items)
            if not items or (total is not None and start >= total):
                break
        return Page(data, total, b"\n".join(raws))

    # --------------------------------------------------------- FortifySource

    def list_applications(self) -> Page:
        return self._all("/projects", {"fields": "id,name"})

    def list_versions(self, application_id: Any) -> Page:
        return self._all(f"/projects/{application_id}/versions", {"fields": "id,name"})

    def issues_page(self, version_id: Any, start: int, limit: int) -> Page:
        doc, raw = self._get(
            f"/projectVersions/{version_id}/issues", {"start": start, "limit": limit, **self.filters.params()}
        )
        return Page(doc.get("data") or [], doc.get("count"), raw)

    def issue_details(self, issue_id: Any) -> Page:
        doc, raw = self._get(f"/issueDetails/{issue_id}")
        data = doc.get("data")
        return Page([data] if isinstance(data, dict) else [], None, raw)

    def issue_count(self, version_id: Any) -> int | None:
        doc, _ = self._get(f"/projectVersions/{version_id}/issues", {"start": 0, "limit": 1, **self.filters.params()})
        count = doc.get("count")
        return int(count) if isinstance(count, int | float) else None


def _network_error(exc: httpx.ConnectError, base: str) -> FortifyError:
    cause = exc.__context__ or exc.__cause__
    text = f"{exc} {cause or ''}"
    if isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in text:
        return FortifyError(
            "Certificat TLS de SSC non reconnu (autorité de certification d'entreprise).",
            "Renseigner [fortify] ca_bundle avec le fichier .pem de l'autorité interne. Ne jamais désactiver TLS.",
        )
    return FortifyError(
        f"SSC injoignable ({base}).",
        "Vérifier l'URL, le VPN et le proxy d'entreprise (variables HTTPS_PROXY / NO_PROXY).",
    )


# ---------------------------------------------------------------------------
# Configuration et jeton
# ---------------------------------------------------------------------------


def token_file(settings: Settings) -> Path:
    return settings.secrets_dir / "fortify.token"


def read_token(settings: Settings) -> tuple[str | None, str]:
    """(jeton, origine). Variable d'environnement d'abord, puis fichier secret local."""
    import os

    env = settings.fortify.get("token_env", "PALADIN_FORTIFY_TOKEN")
    if os.environ.get(env):
        return os.environ[env].strip(), f"variable {env}"
    path = token_file(settings)
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return path.read_text(encoding="utf-8").strip(), "fichier secrets/fortify.token"
    return None, "absent"


def save_token(settings: Settings, token: str) -> Path:
    import contextlib

    path = token_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip(), encoding="utf-8")
    with contextlib.suppress(OSError):  # Windows : ACL du profil utilisateur
        path.chmod(0o600)
    return path


def make_client(settings: Settings, transport: httpx.BaseTransport | None = None) -> SSCClient:
    """Client SSC depuis paladin.toml. `url = "demo://ssc"` : SSC fictif de démonstration."""
    url = (settings.fortify.get("url") or "").strip()
    if not url:
        raise FortifyError(
            "URL SSC non renseignée.", "Renseigner l'URL dans « Prêt pour le travail » ou [fortify] url."
        )
    if url.startswith("demo://"):
        from paladin.fortify.fake_ssc import demo_transport

        transport = transport or demo_transport()
        url = "https://ssc.demo.invalid/ssc"
        from paladin.fortify.fake_ssc import DEMO_TOKEN

        token = DEMO_TOKEN
    else:
        token, _origin = read_token(settings)
        if not token:
            raise FortifyError(
                "Jeton SSC absent.", "Saisir le jeton dans « Prêt pour le travail » ou `Paladin.cmd fortify login`."
            )
    ca = (settings.fortify.get("ca_bundle") or "").strip()
    verify: bool | str = ca if ca else True
    filters = SSCFilters(
        **{k: v for k, v in (settings.fortify.get("filters") or {}).items() if k in SSCFilters.__annotations__}
    )
    return SSCClient(url, token, verify=verify, filters=filters, transport=transport)
