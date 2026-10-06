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
        state = "créée" if result.created else "déjà présente (utiliser --reset pour repartir de zéro)"
        print(f"Démo {state} — données FICTIVES, propositions simulées (aucune connexion GLM).")
        if result.created:
            from paladin import store
            from paladin.importers.pipeline import import_tool

            from paladin.demo import add_simulated_proposals

            for tool in store.list_tools(conn, result.campaign_id):
                print_import_report(import_tool(settings, conn, result.campaign_id, tool["label"]))
            n = add_simulated_proposals(conn, result.campaign_id)
            print(f"{n} proposition(s) SIMULÉE(S) ajoutée(s) pour la démo (aucun modèle appelé).")
    finally:
        conn.close()
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
    url = f"http://{host}:{port}/"
    if getattr(args, "browser", False):
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print("Arrêter : Ctrl+C dans cette fenêtre.")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Le plus simple : ouvre l'espace réel s'il existe, sinon la démo (créée au besoin)."""
    real = default_home().resolve()
    demo_home = default_demo_home().resolve()
    if args.home:
        target = Path(args.home).expanduser().resolve()
    elif (real / "paladin.toml").exists():
        target = real
    else:
        if not (demo_home / "paladin.toml").exists():
            print("Première utilisation : création d'une démonstration avec des données fictives.\n")
            cmd_demo(argparse.Namespace(home=None, reset=False))
            print()
        target = demo_home
        print("Espace de DÉMO (données fictives). Pour une vraie campagne : voir docs/GUIDE.md.")
    return cmd_serve(argparse.Namespace(home=str(target), host=None, port=args.port, demo=False,
                                        browser=not args.no_browser))


def cmd_campaign(args: argparse.Namespace) -> int:
    from paladin.campaigns import CampaignError, create_from_file

    home = _home_arg(args)
    _guard_home(home)
    if not (home / "paladin.toml").exists():
        init_home(home)
    settings = load_settings(home)
    conn = open_database(settings.db_path)
    try:
        cid = create_from_file(settings, conn, Path(args.file))
    except CampaignError as exc:
        print(f"Campagne non créée : {exc}")
        return 2
    finally:
        conn.close()
    print(f"Campagne « {cid} » créée dans {home}.")
    print("Suite : python -m paladin start   (puis « Importer » dans l'interface)")
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


def _open(args: argparse.Namespace, demo: bool = False):
    home = _home_arg(args, demo=demo)
    if not args.home and not demo and not (home / "paladin.toml").exists():
        demo_home = default_demo_home().resolve()
        if (demo_home / "paladin.toml").exists():
            home = demo_home
    settings = load_settings(home)
    if not settings.db_path.exists():
        raise SystemExit(f"Aucune base dans {home}. → `python -m paladin init` ou `python -m paladin demo`.")
    return settings, open_database(settings.db_path)


def print_import_report(report) -> None:
    print(report.summary())
    for src in report.sources:
        print(f"  · {src.role} ({src.kind}) : {src.records} enregistrement(s), complétude {src.completeness} — {src.profile}")
        for note in src.notes:
            print(f"      note : {note}")
        for part in src.unrecognized:
            print(f"      NON RECONNU {part['locator']} : {part['reason']}")
        for part in src.ignored:
            print(f"      ignoré (profil) {part['locator']} : {part['reason']}")
    if report.error:
        print(f"  ! Collecte interrompue : {report.error['message']}\n    → {report.error['action']}")
    if report.blocked:
        print(f"  ! BLOQUÉ : {report.blocked['message']}\n    → {report.blocked['action']}")
        if "proposal" in report.blocked:
            print_proposal(report.blocked["proposal"], report.blocked.get("basis", {}),
                           report.blocked.get("unmapped", []), report.blocked.get("missing", []))


def print_proposal(mapping: dict, basis: dict, unmapped: list, missing: list) -> None:
    print("    Mapping proposé (champ source → clé interne) :")
    for key, spec in mapping.get("fields", {}).items():
        t = spec.get("transform", "text")
        print(f"      {spec['source']!r:28} → {key}{'' if t == 'text' else f' [{t}]'}  ({basis.get(key, 'déclaré')})")
    if mapping.get("comments_from"):
        print(f"      commentaires source : {mapping['comments_from']}")
    if unmapped:
        print(f"    Champs non couverts (conservés en données brutes) : {unmapped}")
    if missing:
        print(f"    Clés importantes non trouvées : {missing}")


def cmd_import(args: argparse.Namespace) -> int:
    from paladin import store
    from paladin.importers.pipeline import import_tool

    settings, conn = _open(args)
    try:
        tools = [args.tool] if args.tool else [t["label"] for t in store.list_tools(conn, args.campaign)]
        code = 0
        for label in tools:
            report = import_tool(settings, conn, args.campaign, label, resume=args.resume)
            print_import_report(report)
            code = code or (3 if report.blocked else 0)
        return code
    finally:
        conn.close()


def cmd_export(args: argparse.Namespace) -> int:
    from paladin.excel.export import export_workbook

    settings, conn = _open(args)
    try:
        result = export_workbook(settings, conn, args.campaign, mode="final" if args.final else "working_copy",
                                 destination=Path(args.to).resolve() if args.to else None)
    finally:
        conn.close()
    if result.status != "verified":
        print(f"Export {result.status} : {result.error}\n→ {result.action}")
        return 4
    s = result.summary
    print(f"Excel à jour : {result.destination}")
    print(f"  cellules écrites {s['cells_written']}, lignes ajoutées {s['rows_appended']}, "
          f"findings à jour {s['findings_up_to_date']}")
    print(f"  bloqués {len(s['blocked'])}, sans cible {len(s['without_target'])}, "
          f"lignes Excel non appariées {len(s['unmatched_rows'])}, valeurs humaines conservées {len(s['preserved_human_values'])}")
    for b in s["blocked"]:
        print(f"    BLOQUÉ {b['sheet']} {b['source_id']} : {b['reason']}")
    if s["tools_without_sheet"]:
        print(f"  outils sans onglet (hors export) : {s['tools_without_sheet']}")
    if result.backup_path:
        print(f"  sauvegarde : {result.backup_path}")
    print(f"  manifeste : {result.manifest_path}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Multi-entrées : détecter les champs d'un fichier et proposer un mapping."""
    from paladin.importers.mapping import propose_mapping
    from paladin.importers.markdown import read_markdown
    from paladin.importers.sarif import read_sarif
    from paladin.importers.tabular import read_csv, read_excel

    path = Path(args.file)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        read = read_excel(path, args.sheet)
    elif suffix in (".csv", ".tsv", ".txt"):
        read = read_csv(path)
    elif suffix in (".sarif", ".json"):
        read = read_sarif(path)
    elif suffix == ".md":
        read = read_markdown(path, args.profile or "heading-kv-v1")
    else:
        print(f"Format non pris en charge : {suffix}. Formats : xlsx, csv, md, sarif.")
        return 2
    print(f"{path.name} : {len(read.records)} enregistrement(s), {len(read.field_names)} champ(s), complétude {read.completeness.value}")
    for part in read.unrecognized:
        print(f"  NON RECONNU {part.locator} : {part.reason}")
    prop = propose_mapping(read.field_names, read.records)
    print_proposal(prop.as_mapping(), {g.key: g.basis for g in prop.guesses}, prop.unmapped, prop.missing)
    print("  (proposition non appliquée : elle devient un profil après validation)")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    from paladin.importers import profiles

    settings, conn = _open(args)
    try:
        if args.action == "list":
            for p in profiles.list_profiles(conn, args.campaign):
                print(f"{p['id']}  {p['name']} v{p['version']}  {p['status']}  ({p['proposed_by']})")
            return 0
        if not args.profile_id:
            print("Identifiant de profil requis.")
            return 2
        prof = profiles.get(conn, args.profile_id)
        if args.action == "show":
            print(f"{prof['name']} v{prof['version']} — {prof['status']} — source {prof['source_kind']}")
            print_proposal(prof["mapping"], {}, [], [])
            print(f"Valider : python -m paladin profile validate {prof['id']}")
            return 0
        if args.action == "validate":
            mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
            prof = profiles.validate(conn, args.profile_id, mapping)
            print(f"Profil {prof['name']} v{prof['version']} validé. Relancer l'import.")
            return 0
    finally:
        conn.close()
    return 2


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
    p.add_argument("--browser", action="store_true", help="Ouvrir le navigateur.")
    p.set_defaults(func=cmd_serve)
    p = add("start", "Démarrer simplement (défaut sans argument) : interface + navigateur.")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_start)
    p = add("campaign", "Créer une campagne réelle depuis un fichier (voir examples/campaign.example.json).")
    p.add_argument("action", choices=["create"])
    p.add_argument("file")
    p.set_defaults(func=cmd_campaign)
    p = add("doctor", "Diagnostic de l'installation et des connecteurs.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)
    add("status", "Lister les campagnes.").set_defaults(func=cmd_status)
    p = add("import", "Importer les sources d'une campagne.")
    p.add_argument("--campaign", default="demo")
    p.add_argument("--tool", help="Un seul outil (libellé).")
    p.add_argument("--resume", action="store_true", help="Reprendre une collecte Fortify interrompue.")
    p.set_defaults(func=cmd_import)
    p = add("export", "Exporter les décisions validées vers l'Excel.")
    p.add_argument("--campaign", default="demo")
    p.add_argument("--final", action="store_true", help="Mettre à jour le classeur cible désigné (sinon copie de travail).")
    p.add_argument("--to", help="Destination explicite.")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("inspect", help="Détecter les champs d'un rapport et proposer un mapping (multi-entrées).")
    p.add_argument("file")
    p.add_argument("--sheet")
    p.add_argument("--profile", help="Profil MD (heading-kv-v1, table-v1).")
    p.set_defaults(func=cmd_inspect)
    p = add("profile", "Profils d'entrée : lister, afficher, valider.")
    p.add_argument("action", choices=["list", "show", "validate"])
    p.add_argument("profile_id", nargs="?")
    p.add_argument("--campaign", default="demo")
    p.add_argument("--mapping", help="Fichier JSON de mapping corrigé à valider.")
    p.set_defaults(func=cmd_profile)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv or ["start"])
    return int(args.func(args) or 0)
