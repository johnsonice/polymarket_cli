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


def _market():
    return SimpleNamespace(
        question="Q", condition_id="0xc",
        outcomes=SimpleNamespace(
            yes=SimpleNamespace(token_id="111", label="Yes", price=Decimal("0.5")),
            no=SimpleNamespace(token_id="222", label="No", price=Decimal("0.5"))),
        trading=SimpleNamespace(minimum_tick_size="0.01", minimum_order_size="5"),
        prices=SimpleNamespace(best_bid="0.49", best_ask="0.51"))


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
