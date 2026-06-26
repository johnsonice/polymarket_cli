"""Unit tests for market/outcome resolution (public client mocked)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from poly.market import live_price, resolve_target


def make_market(yes_token="111", no_token="222", tick="0.01", bid="0.49", ask="0.51"):
    return SimpleNamespace(
        question="Will X happen?",
        condition_id="0xcond",
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id=yes_token, label="Yes", price=Decimal("0.51")),
            no=SimpleNamespace(token_id=no_token, label="No", price=Decimal("0.49")),
        ),
        trading=SimpleNamespace(minimum_tick_size=tick, minimum_order_size="5"),
        prices=SimpleNamespace(best_bid=bid, best_ask=ask),
    )


class _FakePaginator:
    def __init__(self, items):
        self._items = items

    def first_page(self):
        return SimpleNamespace(items=self._items)


class FakePub:
    def __init__(self, market=None, by_token=None, price=None, raise_get=False):
        self._market = market
        self._by_token = by_token
        self._price = price
        self._raise_get = raise_get

    def get_market(self, slug=None, url=None):
        if self._raise_get:
            raise RuntimeError("not found")
        return self._market

    def list_markets(self, clob_token_ids=None):
        return _FakePaginator(self._by_token or [])

    def get_price(self, token_id=None, side=None):
        if self._price is None:
            raise RuntimeError("no price")
        return self._price


def test_resolve_by_slug_picks_yes_token():
    target = resolve_target(FakePub(market=make_market()), slug="x", outcome="yes")
    assert target.token_id == "111"
    assert target.outcome_label == "Yes"
    assert target.tick_size == Decimal("0.01")
    assert target.best_ask == Decimal("0.51")
    assert target.question == "Will X happen?"


def test_resolve_by_slug_picks_no_token():
    target = resolve_target(FakePub(market=make_market()), slug="x", outcome="no")
    assert target.token_id == "222"
    assert target.outcome_label == "No"


def test_resolve_by_token_found_labels_outcome():
    target = resolve_target(FakePub(by_token=[make_market()]), token_id="111")
    assert target.token_id == "111"
    assert target.outcome_label == "Yes"
    assert target.tick_size == Decimal("0.01")


def test_resolve_by_token_not_found_returns_bare_target():
    target = resolve_target(FakePub(by_token=[]), token_id="999")
    assert target.token_id == "999"
    assert target.tick_size is None
    assert target.question is None


def test_resolve_requires_exactly_one_selector():
    with pytest.raises(SystemExit):
        resolve_target(FakePub())  # none
    with pytest.raises(SystemExit):
        resolve_target(FakePub(market=make_market()), slug="x", token_id="111")  # two


def test_resolve_get_market_failure_is_friendly():
    with pytest.raises(SystemExit):
        resolve_target(FakePub(raise_get=True), slug="missing")


def test_resolve_market_without_outcome_token_errors():
    market = make_market()
    market.outcomes.yes = SimpleNamespace(token_id=None, label="Yes")
    with pytest.raises(SystemExit):
        resolve_target(FakePub(market=market), slug="x", outcome="yes")


def test_resolve_by_token_survives_list_markets_failure():
    class RaisingPub(FakePub):
        def list_markets(self, clob_token_ids=None):
            raise RuntimeError("gamma down")

    target = resolve_target(RaisingPub(), token_id="999")
    assert target.token_id == "999"
    assert target.tick_size is None
    assert target.question is None


def test_resolve_by_slug_rejects_non_numeric_token():
    market = make_market(yes_token="not-a-number")
    with pytest.raises(SystemExit):
        resolve_target(FakePub(market=market), slug="x", outcome="yes")


def test_live_price_returns_value_or_none():
    assert live_price(FakePub(price=Decimal("0.5")), "1", "BUY") == Decimal("0.5")
    assert live_price(FakePub(), "1", "BUY") is None
