# tests/test_trade.py
from decimal import Decimal
from types import SimpleNamespace
import pytest
from poly import trade


class FakePub:
    def __init__(self, market=None, by_token=None):
        self._m, self._t = market, by_token or []
    def get_market(self, slug=None, url=None): return self._m
    def list_markets(self, clob_token_ids=None):
        return SimpleNamespace(first_page=lambda: SimpleNamespace(items=self._t))
    def get_price(self, token_id=None, side=None): return Decimal("0.50")


def _market(tick="0.01"):
    return SimpleNamespace(
        question="Q", condition_id="0xc",
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id="111", label="Yes", price=Decimal("0.5")),
            no=SimpleNamespace(token_id="222", label="No", price=Decimal("0.5"))),
        trading=SimpleNamespace(minimum_tick_size=tick, minimum_order_size="5"),
        prices=SimpleNamespace(best_bid="0.49", best_ask="0.51"))


def _fake_signed():
    """A signed-order fake that mirrors the real SignedOrder attribute shape."""
    return SimpleNamespace(
        maker="0xmaker",
        signer="0xsigner",
        token_id="111",
        side="BUY",
        maker_amount="1",
        taker_amount="2",
        order_type="GTC",
        signature_type=3,
        expiration=0,
    )


def _fake_client(signed=None, wallet="0xwallet"):
    """A minimal SecureClient fake: create_limit_order returns signed."""
    s = signed or _fake_signed()
    return SimpleNamespace(
        wallet=wallet,
        create_limit_order=lambda **kw: s,
        create_market_order=lambda **kw: s,
        post_order=lambda x: SimpleNamespace(ok=True, order_id="oid1", status="open"),
        setup_trading_approvals=lambda: None,
    )


def _fake_ctx(fmt="table"):
    return SimpleNamespace(obj=SimpleNamespace(output=fmt))


# --------------------------------------------------------------------------- #
# build_plan tests
# --------------------------------------------------------------------------- #

def test_build_plan_limit_usd_to_size():
    pub = FakePub(by_token=[_market()])
    target, plan = trade.build_plan(side="BUY", market_order=False, token_id="111",
                                    usd="1", price="0.5", pub=pub)
    assert plan.kind == "limit" and str(plan.size) == "2"


def test_market_buy_requires_usd():
    pub = FakePub(market=_market())
    with pytest.raises(SystemExit):
        trade.build_plan(side="BUY", market_order=True, slug="x", size="5", pub=pub)


def test_market_sell_requires_size():
    pub = FakePub(market=_market())
    with pytest.raises(SystemExit):
        trade.build_plan(side="SELL", market_order=True, slug="x", usd="5", pub=pub)


def test_limit_plan_price_rounds_to_boundary_rejected():
    """Price 0.001 rounds to 0.00 with 0.01 tick — must raise SystemExit mentioning 'not tradable'."""
    pub = FakePub(by_token=[_market(tick="0.01")])
    with pytest.raises(SystemExit, match="not tradable"):
        trade.build_plan(side="BUY", market_order=False, token_id="111",
                         price="0.001", usd="1", pub=pub)


# --------------------------------------------------------------------------- #
# run() tests
# --------------------------------------------------------------------------- #

def test_run_dry_run_does_not_post(monkeypatch):
    """dry_run=True must emit preview + signed identity, never call post_order, return 0."""
    pub = FakePub(by_token=[_market()])
    target, plan = trade.build_plan(side="BUY", market_order=False, token_id="111",
                                    usd="1", price="0.5", pub=pub)

    signed = _fake_signed()
    client = _fake_client(signed=signed)
    post_called = []
    client.post_order = lambda x: post_called.append(x) or SimpleNamespace(ok=True)

    emitted = []
    monkeypatch.setattr(trade, "emit", lambda fmt, d: emitted.append(d))

    code = trade.run(
        _fake_ctx(),
        pub=pub,
        secure_factory=lambda: client,
        target=target,
        plan=plan,
        dry_run=True,
        yes=False,
    )

    assert code == 0
    assert not post_called, "post_order must not be called in dry-run mode"
    # Two emit calls: preview dict + signed dict
    assert len(emitted) == 2
    assert emitted[1].get("dry_run") is True


def test_run_non_interactive_aborts(monkeypatch):
    """When yes=False and stdin is closed (EOFError), run() must emit aborted dict and return 1."""
    pub = FakePub(by_token=[_market()])
    target, plan = trade.build_plan(side="BUY", market_order=False, token_id="111",
                                    usd="1", price="0.5", pub=pub)

    client = _fake_client()
    emitted = []
    monkeypatch.setattr(trade, "emit", lambda fmt, d: emitted.append(d))
    # Simulate non-interactive: _confirm raises EOFError by making input raise it
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))

    code = trade.run(
        _fake_ctx(),
        pub=pub,
        secure_factory=lambda: client,
        target=target,
        plan=plan,
        dry_run=False,
        yes=False,
    )

    assert code == 1
    assert any(d.get("aborted") for d in emitted)


def test_run_yes_flag_submits_and_returns_accepted(monkeypatch):
    """yes=True skips confirmation, calls post_order, returns 0 when accepted."""
    pub = FakePub(by_token=[_market()])
    target, plan = trade.build_plan(side="BUY", market_order=False, token_id="111",
                                    usd="1", price="0.5", pub=pub)

    post_calls = []
    signed = _fake_signed()

    def fake_post(x):
        post_calls.append(x)
        return SimpleNamespace(ok=True, order_id="oid99", status="open")

    client = _fake_client(signed=signed)
    client.post_order = fake_post

    emitted = []
    monkeypatch.setattr(trade, "emit", lambda fmt, d: emitted.append(d))

    code = trade.run(
        _fake_ctx(),
        pub=pub,
        secure_factory=lambda: client,
        target=target,
        plan=plan,
        dry_run=False,
        yes=True,
    )

    assert code == 0
    assert len(post_calls) == 1
    assert any("result" in d for d in emitted)


def test_run_yes_flag_returns_1_when_rejected(monkeypatch):
    """yes=True, rejected response → exit code 1."""
    pub = FakePub(by_token=[_market()])
    target, plan = trade.build_plan(side="BUY", market_order=False, token_id="111",
                                    usd="1", price="0.5", pub=pub)

    client = _fake_client()
    client.post_order = lambda x: SimpleNamespace(ok=False, code="ERROR", message="bad")

    monkeypatch.setattr(trade, "emit", lambda fmt, d: None)

    code = trade.run(
        _fake_ctx(),
        pub=pub,
        secure_factory=lambda: client,
        target=target,
        plan=plan,
        dry_run=False,
        yes=True,
    )

    assert code == 1


# --------------------------------------------------------------------------- #
# _submit() approvals retry
# --------------------------------------------------------------------------- #

class _FakeAllowanceError(Exception):
    pass


def test_submit_retries_after_allowance_error(monkeypatch):
    """_submit retries post after setup_trading_approvals when InsufficientAllowanceError is raised."""
    monkeypatch.setattr(trade, "InsufficientAllowanceError", _FakeAllowanceError)

    calls = []

    def fake_post(x):
        if not calls:
            calls.append("first")
            raise _FakeAllowanceError("need approvals")
        calls.append("retry")
        return SimpleNamespace(ok=True, order_id="rid1", status="open")

    approvals_called = []
    client = SimpleNamespace(
        wallet="0xw",
        post_order=fake_post,
        setup_trading_approvals=lambda: approvals_called.append(True),
    )

    emitted = []
    monkeypatch.setattr(trade, "emit", lambda fmt, d: emitted.append(d))
    # Simulate user typing YES for the approvals confirm
    monkeypatch.setattr("builtins.input", lambda _: "YES")

    signed = _fake_signed()
    result = trade._submit(client, signed)

    assert result.ok is True
    assert approvals_called, "setup_trading_approvals must be called"
    assert len(calls) == 2  # first failed, retry succeeded


# --------------------------------------------------------------------------- #
# Output helper unit tests
# --------------------------------------------------------------------------- #

def test_wallet_str_uses_wallet_attr():
    client = SimpleNamespace(wallet="0xabc")
    assert trade._wallet_str(client) == "0xabc"


def test_wallet_str_falls_back_to_unknown():
    assert trade._wallet_str(SimpleNamespace()) == "(unknown)"


def test_fmt_decimal():
    assert trade._fmt(Decimal("2.50")) == "2.5"


def test_fmt_string():
    assert trade._fmt("hello") == "hello"


def test_preview_dict_limit_order():
    pub = FakePub(by_token=[_market()])
    target, plan = trade.build_plan(side="BUY", market_order=False, token_id="111",
                                    usd="1", price="0.5", pub=pub)
    client = SimpleNamespace(wallet="0xw")
    d = trade._preview_dict(target, plan, client, book=Decimal("0.50"))
    assert d["side"] == "BUY"
    assert "price" in d
    assert "size" in d
    assert d["wallet"] == "0xw"


def test_preview_dict_market_buy():
    pub = FakePub(market=_market())
    target, plan = trade.build_plan(side="BUY", market_order=True, slug="x",
                                    usd="5", pub=pub)
    client = SimpleNamespace(wallet="0xw")
    d = trade._preview_dict(target, plan, client, book=None)
    assert "spend" in d
    assert d["book_price"] == "unavailable"


def test_preview_dict_market_sell_with_book():
    pub = FakePub(market=_market())
    target, plan = trade.build_plan(side="SELL", market_order=True, slug="x",
                                    size="10", pub=pub)
    client = SimpleNamespace(wallet="0xw")
    d = trade._preview_dict(target, plan, client, book=Decimal("0.50"))
    assert "shares" in d
    assert "~proceeds" in d


def test_signed_dict_includes_dry_run_flag():
    client = SimpleNamespace(wallet="0xw")
    signed = _fake_signed()
    d = trade._signed_dict(client, signed)
    assert d["dry_run"] is True
    assert d["wallet"] == "0xw"
    assert d["token_id"] == "111"
