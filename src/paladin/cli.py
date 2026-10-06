"""Points d'entrée CLI : `python -m paladin <commande>`."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

from paladin import __version__, doctor
from paladin.config import (
    DEFAULT_HOST,
    default_demo_home,
    default_home,
    init_home,
    is_inside,
    load_settings,
)
from paladin.db import open_database

REPO_ROOT = Path(__file__).resolve().parents[2]
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _configure_stdio() -> None:
    # Consoles Windows en cp1252 : éviter les UnicodeEncodeError sur les accents.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _home_arg(args: argparse.Namespace, demo: bool = False) -> Path:
    if args.home:
        return Path(args.home).expanduser().resolve()
    return (default_demo_home() if demo else default_home()).resolve()


def _guard_home(home: Path) -> None:
    """Les données ne vivent jamais dans le dépôt logiciel."""
    if (REPO_ROOT / ".git").exists() and is_inside(home, REPO_ROOT):
        raise SystemExit(
            f"Refus : le dossier de données {home} est à l'intérieur du dépôt {REPO_ROOT}.\n"
            "→ Choisir un dossier hors du dépôt avec --home ou PALADIN_HOME."
        )


def cmd_init(args: argparse.Namespace) -> int:
    home = _home_arg(args)
    _guard_home(home)
    init_home(home)
    settings = load_settings(home)
    open_database(settings.db_path).close()
    settings.agent_token()
    settings.ui_token()
    print(f"Espace de travail prêt : {home}")
    print(f"Configuration : {settings.config_path}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from paladin.demo import mark_demo_home, reset_demo_home, seed_demo

    home = _home_arg(args, demo=True)
    _guard_home(home)
    if args.reset:
        reset_demo_home(home)
    init_home(home)
    mark_demo_home(home)
    settings = load_settings(home)
    conn = open_database(settings.db_path)
    try:
        result = seed_demo(settings, conn)
    finally:
        conn.close()
    state = "créée" if result.created else "déjà présente (utiliser --reset pour repartir de zéro)"
    print(f"Démo {state} — données FICTIVES, propositions simulées (aucune connexion GLM).")
    print(f"Espace de démo : {home}")
    print(f"Classeur cible : {result.workbook}")
    print(f"Lancer l'interface : python -m paladin serve --home \"{home}\"")
    return 0


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(host: str, preferred: int, attempts: int = 20) -> int:
    for port in range(preferred, preferred + attempts):
        if _port_free(host, port):
            return port
    raise SystemExit(f"Aucun port libre entre {preferred} et {preferred + attempts - 1}. → Utiliser --port.")


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from paladin.web.app import create_app

    home = _home_arg(args, demo=args.demo)
    if not args.home and not args.demo and not (home / "paladin.toml").exists():
        demo_home = default_demo_home().resolve()
        if (demo_home / "paladin.toml").exists():
            print(f"Aucun espace de travail réel dans {home} : ouverture de l'espace de DÉMO.")
            home = demo_home
    _guard_home(home)
    if not (home / "paladin.toml").exists():
        print(f"Espace absent : {home}\n→ Lancer `python -m paladin init` ou `python -m paladin demo`.", file=sys.stderr)
        return 2
    settings = load_settings(home)
    host = args.host or settings.host or DEFAULT_HOST
    if host not in LOOPBACK:
        print(f"Refus : Paladin n'écoute que sur la boucle locale (reçu {host}).", file=sys.stderr)
        return 2
    port = pick_port(host, args.port or settings.port)
    if port != (args.port or settings.port):
        print(f"Port {args.port or settings.port} occupé : utilisation du port {port}.")
    print(f"Paladin {__version__} — http://{host}:{port}/")
    print(f"Données : {home}")
    for check in doctor.run_checks(settings):
        if check.area in {"agent", "fortify"}:
            print(f"Connecteur {check.area} : [{check.status.value}] {check.detail}")
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    home = _home_arg(args)
    settings = load_settings(home)
    checks = doctor.run_checks(settings)
    if args.json:
        print(json.dumps(doctor.to_dicts(checks), indent=2, ensure_ascii=False))
    else:
        print(doctor.render_text(checks))
    if settings.home.exists():
        print(f"\nRapport : {doctor.write_report(settings, checks)}")
    return 1 if any(c.status == doctor.Status.BLOCK for c in checks) else 0


def cmd_status(args: argparse.Namespace) -> int:
    from paladin import store

    home = _home_arg(args)
    settings = load_settings(home)
    if not settings.db_path.exists():
        print(f"Aucune base dans {home}.")
        return 1
    conn = open_database(settings.db_path)
    try:
        for c in store.list_campaigns(conn):
            print(f"{c['id']}\t{c['name']}{' (démo)' if c['is_demo'] else ''}")
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paladin", description="Assistant local de triage AppSec.")
    parser.add_argument("--version", action="version", version=f"paladin {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--home", help="Dossier de données (défaut : PALADIN_HOME ou dossier utilisateur).")
        return p

    add("init", "Créer l'espace de travail local.").set_defaults(func=cmd_init)
    p = add("demo", "Créer l'espace de démonstration (données fictives).")
    p.add_argument("--reset", action="store_true", help="Supprimer et recréer l'espace de démo.")
    p.set_defaults(func=cmd_demo)
    p = add("serve", "Lancer l'interface locale.")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--demo", action="store_true", help="Ouvrir l'espace de démonstration.")
    p.set_defaults(func=cmd_serve)
    p = add("doctor", "Diagnostic de l'installation et des connecteurs.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)
    add("status", "Lister les campagnes.").set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)
