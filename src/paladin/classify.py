"""Classification interne d'un finding : famille, route d'analyse, prochaine étape.

Usage interne uniquement (filtres, contexte de l'agent, file de revue). La
catégorie brute de l'outil reste la seule exportée dans l'Excel. La base de
l'inférence est toujours conservée (`cwe:89`, `keyword:sql injection`) ; sans
indice, la famille reste inconnue plutôt que devinée.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Route d'analyse : quelle méthode de vérification appliquer (section 10 :
# ne pas forcer le schéma source/sink sur une règle sans flux de données).
ROUTE_DATAFLOW = "dataflow"
ROUTE_CRYPTO = "crypto"
ROUTE_SECRET = "secret"  # noqa: S105 — nom de route d'analyse, pas un secret
ROUTE_CONFIG = "config"
ROUTE_DEPENDENCY = "dependency"
ROUTE_GENERIC = "generic"


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    route: str


FAMILIES: dict[str, Family] = {
    f.key: f
    for f in (
        Family("sql_injection", "Injection SQL", ROUTE_DATAFLOW),
        Family("command_injection", "Injection de commande", ROUTE_DATAFLOW),
        Family("code_injection", "Injection de code / désérialisation", ROUTE_DATAFLOW),
        Family("xss", "Cross-site scripting", ROUTE_DATAFLOW),
        Family("path_traversal", "Manipulation de chemin", ROUTE_DATAFLOW),
        Family("ssrf", "SSRF", ROUTE_DATAFLOW),
        Family("open_redirect", "Redirection ouverte", ROUTE_DATAFLOW),
        Family("log_injection", "Injection dans les journaux", ROUTE_DATAFLOW),
        Family("xxe", "XXE", ROUTE_DATAFLOW),
        Family("ldap_xpath_injection", "Injection LDAP / XPath", ROUTE_DATAFLOW),
        Family("weak_crypto", "Cryptographie faible", ROUTE_CRYPTO),
        Family("insecure_random", "Aléa prévisible", ROUTE_CRYPTO),
        Family("hardcoded_secret", "Secret en dur", ROUTE_SECRET),
        Family("vulnerable_dependency", "Dépendance vulnérable", ROUTE_DEPENDENCY),
        Family("security_config", "Configuration de sécurité", ROUTE_CONFIG),
        Family("authn_authz", "Authentification / autorisation", ROUTE_GENERIC),
        Family("error_handling", "Gestion d'erreurs / fuite d'information", ROUTE_GENERIC),
    )
}

_CWE_FAMILY: dict[int, str] = {
    89: "sql_injection",
    564: "sql_injection",
    77: "command_injection",
    78: "command_injection",
    94: "code_injection",
    95: "code_injection",
    502: "code_injection",
    79: "xss",
    80: "xss",
    83: "xss",
    22: "path_traversal",
    23: "path_traversal",
    36: "path_traversal",
    73: "path_traversal",
    918: "ssrf",
    601: "open_redirect",
    117: "log_injection",
    93: "log_injection",
    611: "xxe",
    90: "ldap_xpath_injection",
    643: "ldap_xpath_injection",
    327: "weak_crypto",
    328: "weak_crypto",
    326: "weak_crypto",
    916: "weak_crypto",
    330: "insecure_random",
    338: "insecure_random",
    259: "hardcoded_secret",
    798: "hardcoded_secret",
    321: "hardcoded_secret",
    1104: "vulnerable_dependency",
    1395: "vulnerable_dependency",
    937: "vulnerable_dependency",
    693: "security_config",
    1021: "security_config",
    16: "security_config",
    287: "authn_authz",
    284: "authn_authz",
    285: "authn_authz",
    862: "authn_authz",
    863: "authn_authz",
    209: "error_handling",
    200: "error_handling",
    497: "error_handling",
}

# Mots-clés évalués dans l'ordre (le plus spécifique d'abord).
_KEYWORDS: tuple[tuple[str, str], ...] = (
    (r"sql\s*inj|sqli\b|\bsql\b", "sql_injection"),
    (r"command\s*inj|os\s*command|shell\s*inj", "command_injection"),
    (r"deserial|code\s*inj|\beval\b", "code_injection"),
    (r"cross[-\s]*site\s*script|\bxss\b", "xss"),
    (r"path\s*(manipulation|traversal)|directory\s*traversal", "path_traversal"),
    (r"\bssrf\b|server[-\s]*side\s*request", "ssrf"),
    (r"open\s*redirect|redirect", "open_redirect"),
    (r"log\s*(forging|injection)", "log_injection"),
    (r"\bxxe\b|xml\s*external", "xxe"),
    (r"ldap|xpath", "ldap_xpath_injection"),
    (r"random|predictable", "insecure_random"),
    (r"hash|crypto|cipher|md5|sha-?1\b|\bdes\b", "weak_crypto"),
    (r"password|secret|credential|api[-\s]*key|hard[-\s]*coded", "hardcoded_secret"),
    (r"dependency|vulnerable\s*(library|component|package)|\bcve-\d+", "vulnerable_dependency"),
    (r"content\s*security\s*policy|\bcsp\b|header|cookie|tls|cors", "security_config"),
    (r"authori[sz]|authenticat|access\s*control", "authn_authz"),
    (r"error\s*handling|stack\s*trace|information\s*(leak|exposure)", "error_handling"),
)
_KEYWORDS_RE = tuple((re.compile(p, re.IGNORECASE), fam) for p, fam in _KEYWORDS)

# Prochaine étape de traitement par route : ce qu'il faut vérifier pour décider.
ROUTE_CHECKLIST: dict[str, tuple[str, ...]] = {
    ROUTE_DATAFLOW: (
        "Identifier la source et vérifier si elle est contrôlée par un attaquant",
        "Suivre la propagation jusqu'à l'opération sensible",
        "Vérifier si une protection est réellement appliquée sur ce chemin",
        "Évaluer les conditions d'exécution et l'impact",
    ),
    ROUTE_CRYPTO: (
        "Déterminer l'usage réel de la primitive (sécurité ou non)",
        "Vérifier la sensibilité des données protégées",
        "Vérifier l'existence d'une alternative déjà en place",
    ),
    ROUTE_SECRET: (
        "Vérifier que la valeur est un secret réel et non un exemple",
        "Déterminer si le fichier est livré ou déployé (test, exemple, production)",
        "Vérifier la portée et la rotation possibles du secret",
    ),
    ROUTE_CONFIG: (
        "Localiser la configuration effective (code, serveur, proxy)",
        "Vérifier si le contrôle est assuré ailleurs dans la chaîne",
    ),
    ROUTE_DEPENDENCY: (
        "Confirmer la version réellement embarquée",
        "Vérifier si le code vulnérable est atteignable",
    ),
    ROUTE_GENERIC: ("Lire le code autour de l'emplacement et qualifier le risque",),
}


@dataclass(frozen=True)
class Classification:
    family: str | None
    basis: str | None  # "cwe:89", "keyword:<motif>", None si inconnue
    route: str

    @property
    def label(self) -> str:
        return FAMILIES[self.family].label if self.family else "Famille inconnue"

    @property
    def checklist(self) -> tuple[str, ...]:
        return ROUTE_CHECKLIST[self.route]


def classify(cwe_ids: list[str], *texts: str | None) -> Classification:
    """Classe à partir des CWE puis des textes (catégorie, règle, titre).

    Quand des CWE pointent vers plusieurs familles, la première CWE reconnue
    l'emporte et la base l'indique.
    """
    for cwe in cwe_ids:
        digits = "".join(ch for ch in cwe if ch.isdigit())
        if digits and int(digits) in _CWE_FAMILY:
            fam = _CWE_FAMILY[int(digits)]
            return Classification(fam, f"cwe:{int(digits)}", FAMILIES[fam].route)
    haystack = " ".join(t for t in texts if t)
    for rx, fam in _KEYWORDS_RE:
        m = rx.search(haystack)
        if m:
            return Classification(fam, f"keyword:{m.group(0).lower()}", FAMILIES[fam].route)
    return Classification(None, None, ROUTE_GENERIC)
