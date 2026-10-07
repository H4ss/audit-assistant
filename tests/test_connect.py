"""Connexion plug and play de l'agent et écriture de paladin.toml."""

import os
import sys
import tomllib
from pathlib import Path

import pytest

from paladin.agent import connect
from paladin.config import load_settings, set_config_value

FAKE = Path(__file__).parent / "fakes" / "fake_opencode.py"


@pytest.fixture()
def fake_opencode(tmp_path, monkeypatch):
    """Un exécutable `opencode` factice dans le PATH (script Python)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if sys.platform == "win32":
        (bindir / "opencode.cmd").write_text(f'@"{sys.executable}" "{FAKE}" %*\n', encoding="utf-8")
    else:
        exe = bindir / "opencode"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    return bindir


def test_set_config_value_keeps_comments_and_validity(settings):
    path = settings.config_path
    set_config_value(path, "agent", "model", "zai-corp/glm-5.3")
    set_config_value(path, "fortify", "url", "https://ssc.corp/ssc")
    set_config_value(path, "nouvelle", "cle", 3)
    text = path.read_text(encoding="utf-8")
    assert "# Configuration locale Paladin" in text and "boucle locale uniquement" in text
    data = tomllib.loads(text)
    assert data["agent"]["model"] == "zai-corp/glm-5.3" and data["fortify"]["url"] == "https://ssc.corp/ssc"
    assert data["nouvelle"]["cle"] == 3 and text.count("model =") == 1


def test_detect_lists_models_glm_first(settings, fake_opencode):
    info = connect.detect(settings)
    assert info.version == "2.0.22"
    assert [m.id for m in info.models][:2] == ["zai-corp/glm-4.5-air", "zai-corp/glm-5.3"]
    assert info.models[-1].id == "other/big-model" and info.default_model == "zai-corp/glm-5.3"


def test_smoke_test_ok_and_saved(settings, fake_opencode, monkeypatch):
    monkeypatch.setenv("FAKE_OPENCODE_MODE", "smoke_ok")
    res = connect.smoke_test(settings, "zai-corp/glm-5.3")
    assert res.ok and res.answer == "OK" and res.cost_usd == pytest.approx(0.0004)
    connect.save_model(settings, "zai-corp/glm-5.3")
    assert load_settings(settings.home).agent["model"] == "zai-corp/glm-5.3"


def test_smoke_test_explains_missing_provider_connection(settings, fake_opencode, monkeypatch):
    monkeypatch.setenv("FAKE_OPENCODE_MODE", "smoke_auth")
    res = connect.smoke_test(settings, "zai-corp/glm-5.3")
    assert not res.ok and "opencode auth login" in res.action and "zai-corp" in res.action


def test_workspace_config_has_no_provider_block(settings):
    from paladin.agent.workspace import opencode_config

    cfg = opencode_config("zai-corp/glm-5.3")
    assert "provider" not in cfg and cfg["permission"]["*"] == "deny"
