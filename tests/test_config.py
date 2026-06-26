import json
import pytest
from poly import config


def test_resolve_prefers_flag_then_env_then_config():
    assert config.resolve_private_key(flag="0xf", env="0xe", config="0xc") == "0xf"
    assert config.resolve_private_key(flag=None, env="0xe", config="0xc") == "0xe"
    assert config.resolve_private_key(flag=None, env=None, config="0xc") == "0xc"
    assert config.resolve_private_key() is None


def test_save_config_is_chmod_600(tmp_path):
    p = tmp_path / "config.json"
    config.save_config({"private_key": "0xabc", "signature_type": 3}, path=p)
    assert json.loads(p.read_text())["private_key"] == "0xabc"
    assert (p.stat().st_mode & 0o777) == 0o600


def test_load_settings_requires_key(tmp_path, monkeypatch):
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    with pytest.raises(SystemExit):
        config.load_settings(path=tmp_path / "missing.json")


def test_load_settings_normalizes_0x_and_defaults_type(tmp_path):
    p = tmp_path / "config.json"
    config.save_config({"private_key": "abc"}, path=p)
    s = config.load_settings(path=p)
    assert s.private_key == "0xabc"
    assert s.signature_type == 3
