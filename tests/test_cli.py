"""Tests for the CLI orchestration (run_order) with injected fakes."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from polymarket import InsufficientAllowanceError

from poly import cli


def make_market(yes_token="111", no_token="222", tick="0.01"):
    return SimpleNamespace(
        question="Will X happen?",
        condition_id="0xcond",
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id=yes_token, label="Yes", price=Decimal("0.51")),
            no=SimpleNamespace(token_id=no_token, label="No", price=Decimal("0.49")),
        ),
        trading=SimpleNamespace(minimum_tick_size=tick, minimum_order_size="5"),
        prices=SimpleNamespace(best_bid="0.49", best_ask="0.51"),
    )


def _signed(kwargs):
    """Mirror the REAL SignedOrder shape: no price/size attrs, uses *_amount."""
    return SimpleNamespace(
        maker="0xDEPOSITWALLET",
        signer="0xDEPOSITWALLET",
        token_id=kwargs.get("token_id"),
        side=kwargs.get("side"),
        maker_amount="1000000",
        taker_amount="2000000",
        order_type=kwargs.get("order_type", "GTC"),
    )


class FakePub:
    def __init__(self, market=None, by_token=None):
        self._market = market
        self._by_token = by_token or []

    def get_market(self, slug=None, url=None):
        return self._market

    def list_markets(self, clob_token_ids=None):
        return SimpleNamespace(first_page=lambda: SimpleNamespace(items=self._by_token))

    def get_price(self, token_id=None, side=None):
        return Decimal("0.50")


class FakeSecureClient:
    wallet = "0xDEPOSITWALLET"

    def __init__(self, response=None, post_raises=None, post_raises_once=None):
        self._response = response or SimpleNamespace(ok=True, order_id="ok1", status="MATCHED")
        self._post_raises = post_raises
        self._post_raises_once = post_raises_once
        self.created = []
        self.posted = []
        self.approvals_called = False

    def create_limit_order(self, **kwargs):
        self.created.append(("limit", kwargs))
        return _signed(kwargs)

    def create_market_order(self, **kwargs):
        self.created.append(("market", kwargs))
        return _signed(kwargs)

    def post_order(self, signed):
        if self._post_raises_once is not None:
            exc, self._post_raises_once = self._post_raises_once, None
            raise exc
        if self._post_raises is not None:
            raise self._post_raises
        self.posted.append(signed)
        return self._response

    def setup_trading_approvals(self):
        self.approvals_called = True


def _args(argv):
    return cli.build_parser().parse_args(argv)


def _run(argv, pub, client):
    return cli.run_order(_args(argv), public_client=pub, make_secure_client=lambda: client)


# --- limit happy paths --------------------------------------------------------

def test_dry_run_limit_does_not_post():
    client = FakeSecureClient()
    code = _run(["buy", "--slug", "x", "--usd", "1", "--price", "0.5", "--dry-run"],
                FakePub(market=make_market()), client)
    assert code == 0
    assert client.created and client.created[0][0] == "limit"
    assert client.posted == []


def test_yes_limit_buy_submits_strings():
    client = FakeSecureClient()
    code = _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5", "--yes"],
                FakePub(by_token=[make_market()]), client)
    assert code == 0
    assert len(client.posted) == 1
    _, kwargs = client.created[0]
    assert kwargs["price"] == "0.5" and isinstance(kwargs["price"], str)
    assert kwargs["size"] == "5"


def test_rejected_order_returns_exit_1():
    client = FakeSecureClient(response=SimpleNamespace(ok=False, code="BAD", message="no"))
    code = _run(["sell", "--token-id", "111", "--size", "5", "--price", "0.5", "--yes"],
                FakePub(by_token=[make_market()]), client)
    assert code == 1


# --- limit validation ---------------------------------------------------------

def test_limit_without_price_errors():
    with pytest.raises(SystemExit):
        _run(["buy", "--slug", "x", "--usd", "1"], FakePub(market=make_market()), FakeSecureClient())


def test_limit_rejects_non_gtc_order_type():
    with pytest.raises(SystemExit):
        _run(["buy", "--slug", "x", "--usd", "1", "--price", "0.5", "--order-type", "FAK"],
             FakePub(market=make_market()), FakeSecureClient())


def test_limit_price_rounding_to_one_is_rejected():
    # 0.999 at tick 0.01 rounds to 1.00 -> not tradable, friendly SystemExit.
    with pytest.raises(SystemExit):
        _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.999"],
             FakePub(by_token=[make_market()]), FakeSecureClient())


# --- market side-aware mapping ------------------------------------------------

def test_market_buy_requires_usd_not_size():
    with pytest.raises(SystemExit):
        _run(["buy", "--slug", "x", "--size", "10", "--market"],
             FakePub(market=make_market()), FakeSecureClient())


def test_market_sell_requires_size_not_usd():
    with pytest.raises(SystemExit):
        _run(["sell", "--slug", "x", "--usd", "5", "--market"],
             FakePub(market=make_market()), FakeSecureClient())


def test_market_buy_sets_amount_and_default_max_spend():
    client = FakeSecureClient()
    code = _run(["buy", "--slug", "x", "--usd", "2", "--market", "--yes"],
                FakePub(market=make_market()), client)
    assert code == 0
    kind, kwargs = client.created[0]
    assert kind == "market"
    assert kwargs["amount"] == "2" and "shares" not in kwargs
    assert kwargs["max_spend"] == "2"  # defaults to --usd


def test_market_buy_respects_explicit_max_spend():
    client = FakeSecureClient()
    _run(["buy", "--slug", "x", "--usd", "2", "--market", "--max-spend", "3", "--yes"],
         FakePub(market=make_market()), client)
    _, kwargs = client.created[0]
    assert kwargs["max_spend"] == "3"


def test_market_sell_sets_shares_only():
    client = FakeSecureClient()
    code = _run(["sell", "--slug", "x", "--size", "10", "--market", "--yes"],
                FakePub(market=make_market()), client)
    assert code == 0
    _, kwargs = client.created[0]
    assert kwargs["shares"] == "10" and "amount" not in kwargs


def test_market_with_price_errors():
    with pytest.raises(SystemExit):
        _run(["buy", "--slug", "x", "--usd", "1", "--market", "--price", "0.5"],
             FakePub(market=make_market()), FakeSecureClient())


# --- confirmation gate --------------------------------------------------------

def test_confirmation_abort_does_not_post(monkeypatch):
    client = FakeSecureClient()
    monkeypatch.setattr("builtins.input", lambda _p="": "no")
    code = _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5"],
                FakePub(by_token=[make_market()]), client)
    assert code == 1 and client.posted == []


def test_confirmation_yes_submits(monkeypatch):
    client = FakeSecureClient()
    monkeypatch.setattr("builtins.input", lambda _p="": "YES")
    code = _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5"],
                FakePub(by_token=[make_market()]), client)
    assert code == 0 and len(client.posted) == 1


def test_confirmation_eof_does_not_submit(monkeypatch):
    client = FakeSecureClient()
    def _raise(_prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", _raise)
    code = _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5"],
                FakePub(by_token=[make_market()]), client)
    assert code == 1 and client.posted == []


@pytest.mark.parametrize("text,expected", [
    ("YES", True), (" YES ", True), ("yes", False), ("Y", False), ("YESS", False), ("", False),
])
def test_confirm_requires_exact_yes(monkeypatch, text, expected):
    monkeypatch.setattr("builtins.input", lambda _p="": text)
    assert cli._confirm("? ") is expected


# --- approvals retry path (on-chain) -----------------------------------------

def test_approvals_retry_then_succeeds(monkeypatch):
    client = FakeSecureClient(post_raises_once=InsufficientAllowanceError("no allowance"))
    monkeypatch.setattr("builtins.input", lambda _p="": "YES")
    code = _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5", "--yes"],
                FakePub(by_token=[make_market()]), client)
    assert client.approvals_called is True
    assert len(client.posted) == 1
    assert code == 0


def test_approvals_declined_aborts_without_posting(monkeypatch):
    client = FakeSecureClient(post_raises_once=InsufficientAllowanceError("no allowance"))
    monkeypatch.setattr("builtins.input", lambda _p="": "no")
    with pytest.raises(SystemExit):
        _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5", "--yes"],
             FakePub(by_token=[make_market()]), client)
    assert client.approvals_called is False
    assert client.posted == []


def test_non_approval_error_is_not_swallowed():
    client = FakeSecureClient(post_raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5", "--yes"],
             FakePub(by_token=[make_market()]), client)
    assert client.approvals_called is False
    assert client.posted == []


# --- wallet override validation ----------------------------------------------

def test_wallet_override_rejects_bad_address():
    with pytest.raises(SystemExit):
        _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5", "--wallet", "nope"],
             FakePub(by_token=[make_market()]), FakeSecureClient())


def test_wallet_override_accepts_valid_address():
    client = FakeSecureClient()
    addr = "0x" + "a" * 40
    code = _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.5", "--wallet", addr, "--yes"],
                FakePub(by_token=[make_market()]), client)
    assert code == 0


# --- preview notes (safety-relevant) -----------------------------------------

def test_preview_warns_when_price_adjusted_to_tick(capsys):
    # 0.523 at tick 0.01 -> 0.52; the user must see the adjustment.
    _run(["buy", "--token-id", "111", "--size", "5", "--price", "0.523", "--dry-run"],
         FakePub(by_token=[make_market(tick="0.01")]), FakeSecureClient())
    out = capsys.readouterr().out
    assert "price adjusted" in out and "0.52" in out


def test_preview_warns_when_tick_assumed_for_unknown_token(capsys):
    # token not found -> tick unknown -> assumed 0.01, user is warned.
    _run(["buy", "--token-id", "999", "--size", "5", "--price", "0.5", "--dry-run"],
         FakePub(by_token=[]), FakeSecureClient())
    out = capsys.readouterr().out
    assert "tick size unknown" in out
