# tests/test_buy_sell.py
from decimal import Decimal
from types import SimpleNamespace
from typer.testing import CliRunner
from poly.cli import app
from poly import context

runner = CliRunner()


class FakePub:
    def list_markets(self, clob_token_ids=None): return SimpleNamespace(first_page=lambda: SimpleNamespace(items=[]))
    def get_price(self, token_id=None, side=None): return Decimal("0.5")


class FakeSecure:
    wallet = "0xW"
    def create_limit_order(self, **k):
        return SimpleNamespace(maker="0xW", signer="0xW", token_id=k["token_id"], side=k["side"],
                               maker_amount="1", taker_amount="2", order_type="GTC")


def test_buy_dry_run(monkeypatch):
    monkeypatch.setattr(context, "secure", lambda ctx: FakeSecure())
    monkeypatch.setattr(context, "public", lambda ctx: FakePub())
    result = runner.invoke(app, ["buy", "--token-id", "111", "--size", "5", "--price", "0.5", "--dry-run"])
    assert result.exit_code == 0
    assert "BUY" in result.output
    assert "111" in result.output
    assert "dry_run" in result.output
