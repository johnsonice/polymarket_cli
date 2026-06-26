# tests/test_wallet.py
import json
from types import SimpleNamespace

from typer.testing import CliRunner
from poly.cli import app
from poly import config, context
import poly.groups.wallet as wallet_mod

runner = CliRunner()


def test_import_writes_key(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setattr(wallet_mod, "CONFIG_PATH", p)
    result = runner.invoke(app, ["wallet", "import", "0x" + "a" * 64])
    assert result.exit_code == 0
    assert json.loads(p.read_text())["private_key"] == "0x" + "a" * 64


def test_address_requires_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "none.json")
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    result = runner.invoke(app, ["wallet", "address"])
    assert result.exit_code != 0


def test_create_generates_key(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setattr(wallet_mod, "CONFIG_PATH", p)
    result = runner.invoke(app, ["wallet", "create"])
    assert result.exit_code == 0
    saved = json.loads(p.read_text())
    assert "private_key" in saved
    assert saved["private_key"].startswith("0x")
    assert len(saved["private_key"]) == 66  # 0x + 64 hex chars


def test_create_blocked_when_key_exists(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"private_key": "0x" + "b" * 64}))
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setattr(wallet_mod, "CONFIG_PATH", p)
    result = runner.invoke(app, ["wallet", "create"])
    assert result.exit_code != 0


def test_show_does_not_print_key(tmp_path, monkeypatch):
    raw_key = "0x" + "a" * 64
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"private_key": raw_key}))
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setattr(wallet_mod, "CONFIG_PATH", p)
    # avoid a real network call for the deposit wallet
    monkeypatch.setattr(context, "secure", lambda ctx: SimpleNamespace(wallet="0xDEPOSIT"))
    result = runner.invoke(app, ["wallet", "show"])
    assert result.exit_code == 0
    assert "signer_eoa" in result.output
    assert "0xDEPOSIT" in result.output
    assert raw_key not in result.output


def test_reset_requires_force(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"private_key": "0x" + "c" * 64}))
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setattr(wallet_mod, "CONFIG_PATH", p)
    result = runner.invoke(app, ["wallet", "reset"])
    assert result.exit_code != 0
    assert p.exists()


def test_reset_force_deletes(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"private_key": "0x" + "d" * 64}))
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setattr(wallet_mod, "CONFIG_PATH", p)
    result = runner.invoke(app, ["wallet", "reset", "--force"])
    assert result.exit_code == 0
    assert not p.exists()
