from types import SimpleNamespace
from typer.testing import CliRunner
from poly.cli import app
from poly import context
from poly.groups import data as data_mod

runner = CliRunner()


class FakePub:
    def list_positions(self, user=None, page_size=20):
        return SimpleNamespace(first_page=lambda: SimpleNamespace(items=[{"outcome": "Yes", "size": "5"}], has_next=False))

    def get_portfolio_values(self, user=None):
        return {"total": "100.50", "user": user}


def test_positions_json(monkeypatch):
    monkeypatch.setattr(context, "public", lambda ctx: FakePub())
    result = runner.invoke(app, ["-o", "json", "data", "positions", "0xWALLET"])
    assert result.exit_code == 0 and "Yes" in result.output


def test_value_calls_get_portfolio_values(monkeypatch):
    monkeypatch.setattr(context, "public", lambda ctx: FakePub())
    result = runner.invoke(app, ["-o", "json", "data", "value", "0xSOMEWALLET"])
    assert result.exit_code == 0
    assert "100.50" in result.output


def test_resolve_user_defaults_to_deposit_wallet(monkeypatch):
    """_resolve_user falls back to the SDK-derived DEPOSIT wallet, not the EOA."""
    fake_secure = SimpleNamespace(wallet="0xDEPOSITWALLET")
    monkeypatch.setattr(context, "secure", lambda ctx: fake_secure)
    ctx = SimpleNamespace(obj=SimpleNamespace(private_key=None))
    assert data_mod._resolve_user(ctx, address=None) == "0xDEPOSITWALLET"


def test_resolve_user_prefers_explicit_address(monkeypatch):
    """An explicit address wins and never builds a secure client."""
    def _boom(ctx):
        raise AssertionError("secure() must not be called when an address is given")
    monkeypatch.setattr(context, "secure", _boom)
    ctx = SimpleNamespace(obj=SimpleNamespace(private_key=None))
    assert data_mod._resolve_user(ctx, address="0xABC") == "0xABC"
