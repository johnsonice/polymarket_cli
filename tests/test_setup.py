# tests/test_setup.py
import json
from typer.testing import CliRunner
from poly.cli import app
from poly import config
import poly.groups.setup as setup_mod

runner = CliRunner()


def test_setup_imports_given_key(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setattr(setup_mod, "CONFIG_PATH", p)
    result = runner.invoke(app, ["setup", "--private-key", "0x" + "b" * 64])
    assert result.exit_code == 0
    assert json.loads(p.read_text())["private_key"] == "0x" + "b" * 64
