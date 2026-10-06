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
        page = httpx.get(f"http://127.0.0.1:{port}/", timeout=5)
        assert "Démo ShopApp" in page.text
    finally:
        proc.terminate()
        proc.wait(timeout=15)
