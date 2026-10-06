import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from paladin import cli
from paladin.demo import DEMO_MARKER


def test_init_refuses_home_inside_repo():
    inside = cli.REPO_ROOT / "paladin-data"
    if not (cli.REPO_ROOT / ".git").exists():
        pytest.skip("pas de checkout Git")
    with pytest.raises(SystemExit):
        cli.main(["init", "--home", str(inside)])
    assert not inside.exists()


def test_demo_is_idempotent_and_separate(home, capsys):
    demo_home = home.with_name(home.name + "-demo")
    assert cli.main(["demo"]) == 0
    assert (demo_home / DEMO_MARKER).is_file()
    assert not home.exists()  # l'espace réel n'est pas touché
    assert cli.main(["demo"]) == 0
    assert "déjà présente" in capsys.readouterr().out
    assert cli.main(["demo", "--reset"]) == 0
    assert (demo_home / "campaigns" / "demo" / "inputs" / "audit_shopapp_demo.xlsx").is_file()


def test_reset_refuses_unmarked_directory(tmp_path):
    victim = tmp_path / "not-demo"
    victim.mkdir()
    (victim / "precious.txt").write_text("x")
    with pytest.raises(RuntimeError):
        cli.main(["demo", "--reset", "--home", str(victim)])
    assert (victim / "precious.txt").exists()


def test_doctor_runs(home, capsys):
    cli.main(["init"])
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert code == 0
    assert "système/python" in out
    assert "fortify/configuration" in out


def test_pick_port_skips_busy_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert cli.pick_port("127.0.0.1", busy) != busy


def test_serve_refuses_non_loopback(home):
    cli.main(["init"])
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_starts_and_stops(home: Path):
    """Démarrage / arrêt réel du service (exigé par la CI, section 23.3)."""
    assert cli.main(["demo"]) == 0
    port = _free_port()
    env = dict(os.environ, PALADIN_HOME=str(home))
    proc = subprocess.Popen(
        [sys.executable, "-m", "paladin", "serve", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if proc.poll() is not None or time.monotonic() > deadline:
                out = proc.stdout.read() if proc.stdout else ""
                pytest.fail(f"Service non démarré : {out}")
            time.sleep(0.2)
        page = httpx.get(f"http://127.0.0.1:{port}/", timeout=5, follow_redirects=True)
        assert "Démo ShopApp" in page.text
    finally:
        proc.terminate()
        proc.wait(timeout=15)


def test_inspect_proposes_mapping_for_unknown_csv(tmp_path, capsys):
    p = tmp_path / "rapport.csv"
    p.write_text("Ref,Titre,Gravité,Fichier,Ligne\nZ-1,XSS,High,a/b.py,3\n", encoding="utf-8")
    assert cli.main(["inspect", str(p)]) == 0
    out = capsys.readouterr().out
    assert "'Gravité'" in out and "criticality_raw" in out and "non appliquée" in out


def test_demo_import_validate_profile_and_export(home, capsys):
    assert cli.main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "ToolC" in out and "BLOQUÉ" in out
    pid = out.split("profile show ")[1].split()[0]
    assert cli.main(["profile", "validate", pid]) == 0
    assert cli.main(["import", "--tool", "ToolC"]) == 0
    assert "NON RECONNU" in capsys.readouterr().out
    assert cli.main(["export"]) == 0
    assert "Excel à jour" in capsys.readouterr().out


def test_no_argument_means_start_and_creates_demo(home, monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli, "cmd_serve", lambda a: seen.setdefault("args", a) and 0)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "Première utilisation" in out and "DÉMO" in out
    assert seen["args"].browser is True and seen["args"].home.endswith("-demo")


def test_campaign_create_from_example_shape(home, tmp_path, capsys):
    import json

    from openpyxl import Workbook

    (tmp_path / "repo").mkdir()
    Workbook().save(tmp_path / "cible.xlsx")
    (tmp_path / "rapport.csv").write_text("Ref,Titre\nX-1,XSS\n", encoding="utf-8")
    desc = {"id": "essai", "name": "Essai", "target_workbook": "cible.xlsx",
            "repos": [{"name": "repo", "path": "repo"}],
            "tools": [{"label": "ToolX", "kind": "csv", "sheet_name": None,
                       "sources": [{"role": "findings", "kind": "csv", "path": "rapport.csv"}]}]}
    f = tmp_path / "campagne.json"
    f.write_text(json.dumps(desc), encoding="utf-8")
    assert cli.main(["campaign", "create", str(f)]) == 0
    assert cli.main(["campaign", "create", str(f)]) == 2  # déjà existante
    assert "existe déjà" in capsys.readouterr().out
    desc["id"], desc["target_workbook"] = "autre", "absent.xlsx"
    f.write_text(json.dumps(desc), encoding="utf-8")
    assert cli.main(["campaign", "create", str(f)]) == 2
    assert "target_workbook" in capsys.readouterr().out


def test_example_campaign_file_is_valid_json():
    import json

    data = json.loads((cli.REPO_ROOT / "examples" / "campaign.example.json").read_text(encoding="utf-8"))
    assert {t["kind"] for t in data["tools"]} <= {"excel_md", "csv"}
