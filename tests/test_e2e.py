"""Test navigateur réel (opt-in) : PALADIN_E2E=1, Chrome/Chromium et Node >= 22 requis."""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from paladin import cli

pytestmark = pytest.mark.skipif(os.environ.get("PALADIN_E2E") != "1", reason="E2E opt-in : PALADIN_E2E=1")

CHROME = next(
    (c for c in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser", "chrome") if shutil.which(c)),
    None,
)


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url: str) -> None:
    for _ in range(100):
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.2)
    pytest.fail(f"{url} injoignable")


def test_keyboard_flow_in_real_browser(home: Path, tmp_path: Path):
    if not CHROME or not shutil.which("node"):
        pytest.skip("Chrome/Chromium ou Node introuvable")
    assert cli.main(["demo"]) == 0
    app_port, cdp_port = _port(), _port()
    env = dict(os.environ, PALADIN_HOME=str(home))
    server = subprocess.Popen(
        [sys.executable, "-m", "paladin", "serve", "--port", str(app_port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    browser = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={tmp_path / 'chrome'}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait(f"http://127.0.0.1:{app_port}/health")
        _wait(f"http://127.0.0.1:{cdp_port}/json/version")
        script = Path(__file__).parent / "e2e" / "keyboard.mjs"
        run = subprocess.run(
            ["node", str(script), f"http://127.0.0.1:{app_port}", str(cdp_port)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        print(run.stdout)
        if run.returncode != 0 and os.environ.get("GITHUB_ACTIONS"):
            for line in (run.stdout + run.stderr).splitlines()[-25:]:  # annotations lisibles sans authentification
                print(f"::error title=E2E::{line}")
        assert run.returncode == 0, run.stdout + run.stderr
    finally:
        browser.terminate()
        server.terminate()
        browser.wait(timeout=15)
        server.wait(timeout=15)
