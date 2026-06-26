"""Unit tests for order validation, sizing, rounding, and submission helpers."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from poly import orders


# --- validation ---------------------------------------------------------------

@pytest.mark.parametrize("price", ["0.01", "0.5", "0.99", 0.5])
def test_validate_price_accepts_values_between_0_and_1(price):
    assert orders.validate_price(price) == Decimal(str(price))


@pytest.mark.parametrize("price", ["0", "1", "-0.1", "1.5"])
def test_validate_price_rejects_out_of_range(price):
    with pytest.raises(ValueError):
        orders.validate_price(price)


def test_validate_price_rejects_non_numeric():
    with pytest.raises(ValueError):
        orders.validate_price("abc")


@pytest.mark.parametrize("size", ["1", "0.5", 10])
def test_validate_size_accepts_positive(size):
    assert orders.validate_size(size) == Decimal(str(size))


@pytest.mark.parametrize("size", ["0", "-1"])
def test_validate_size_rejects_non_positive(size):
    with pytest.raises(ValueError):
        orders.validate_size(size)


@pytest.mark.parametrize("side,expected", [("buy", "BUY"), ("SELL", "SELL"), ("Buy", "BUY")])
def test_normalize_side(side, expected):
    assert orders.normalize_side(side) == expected


def test_normalize_side_rejects_garbage():
    with pytest.raises(ValueError):
        orders.normalize_side("hold")


# --- sizing & rounding --------------------------------------------------------

def test_compute_size_from_usd_floors_to_two_decimals():
    # 1 / 0.51 = 1.9607... -> floored to 1.96
    assert orders.compute_size_from_usd("1", "0.51") == Decimal("1.96")


def test_compute_size_from_usd_never_overspends():
    size = orders.compute_size_from_usd("1", "0.51")
    assert size * Decimal("0.51") <= Decimal("1")


def test_compute_size_from_usd_rejects_non_positive_usd():
    with pytest.raises(ValueError):
        orders.compute_size_from_usd("0", "0.5")


@pytest.mark.parametrize(
    "price,tick,expected",
    [
        ("0.523", "0.01", Decimal("0.52")),
        ("0.525", "0.01", Decimal("0.53")),
        ("0.5237", "0.001", Decimal("0.524")),
        ("0.52", None, Decimal("0.52")),
    ],
)
def test_round_to_tick(price, tick, expected):
    assert orders.round_to_tick(price, tick) == expected


def test_normalize_tick_defaults_unknown_to_one_cent():
    assert orders.normalize_tick("0.07") == Decimal("0.01")
    assert orders.normalize_tick(None) == Decimal("0.01")
    assert orders.normalize_tick("0.001") == Decimal("0.001")


@pytest.mark.parametrize(
    "value,expected",
    [(Decimal("0.5000"), "0.5"), (Decimal("10"), "10"), (Decimal("1.960"), "1.96")],
)
def test_decimal_str_strips_trailing_zeros(value, expected):
    assert orders.decimal_str(value) == expected


# --- response helpers ---------------------------------------------------------

def test_is_accepted_and_describe():
    accepted = SimpleNamespace(ok=True, order_id="abc", status="MATCHED")
    rejected = SimpleNamespace(ok=False, code="X", message="nope")
    assert orders.is_accepted(accepted) is True
    assert orders.is_accepted(rejected) is False
    assert "ACCEPTED" in orders.describe_response(accepted)
    assert "abc" in orders.describe_response(accepted)
    assert "REJECTED" in orders.describe_response(rejected)
    assert "nope" in orders.describe_response(rejected)


# --- order construction passes STRINGS to the SDK -----------------------------

class _CaptureClient:
    def __init__(self):
        self.calls = []

    def create_limit_order(self, **kwargs):
        self.calls.append(("limit", kwargs))
        return SimpleNamespace(**kwargs)

    def create_market_order(self, **kwargs):
        self.calls.append(("market", kwargs))
        return SimpleNamespace(**kwargs)

    def place_market_order(self, **kwargs):
        self.calls.append(("place_market", kwargs))
        return SimpleNamespace(ok=True, order_id="m1", status="MATCHED")

    def post_order(self, signed):
        self.calls.append(("post", signed))
        return SimpleNamespace(ok=True, order_id="p1", status="MATCHED")


def test_build_signed_limit_order_sends_strings():
    client = _CaptureClient()
    orders.build_signed_limit_order(client, token_id=123, price=Decimal("0.52"), size=Decimal("10"), side="buy")
    kind, kwargs = client.calls[0]
    assert kind == "limit"
    assert kwargs["token_id"] == "123"
    assert kwargs["price"] == "0.52" and isinstance(kwargs["price"], str)
    assert kwargs["size"] == "10" and isinstance(kwargs["size"], str)
    assert kwargs["side"] == "BUY"


def test_build_signed_limit_order_validates():
    client = _CaptureClient()
    with pytest.raises(ValueError):
        orders.build_signed_limit_order(client, token_id=1, price="1.2", size="5", side="buy")


def test_market_kwargs_requires_exactly_one_of_amount_or_shares():
    client = _CaptureClient()
    with pytest.raises(ValueError):
        orders.build_signed_market_order(client, token_id=1, side="buy")  # neither
    with pytest.raises(ValueError):
        orders.build_signed_market_order(client, token_id=1, side="buy", amount="1", shares="1")  # both


def test_market_kwargs_rejects_bad_order_type():
    client = _CaptureClient()
    with pytest.raises(ValueError):
        orders.build_signed_market_order(client, token_id=1, side="buy", amount="1", order_type="GTC")


def test_place_market_order_sends_strings():
    client = _CaptureClient()
    orders.place_market_order(client, token_id=9, side="buy", amount=Decimal("2"), order_type="FAK")
    kind, kwargs = client.calls[0]
    assert kind == "place_market"
    assert kwargs["amount"] == "2" and isinstance(kwargs["amount"], str)
    assert kwargs["side"] == "BUY"
    assert kwargs["order_type"] == "FAK"


# --- market order side semantics & money guards -------------------------------

def test_market_buy_rejects_shares():
    client = _CaptureClient()
    with pytest.raises(ValueError):
        orders.build_signed_market_order(client, token_id=1, side="buy", shares="10")


def test_market_sell_rejects_amount():
    client = _CaptureClient()
    with pytest.raises(ValueError):
        orders.build_signed_market_order(client, token_id=1, side="sell", amount="5")


def test_market_sell_with_shares_serializes_string_only():
    client = _CaptureClient()
    orders.build_signed_market_order(client, token_id=7, side="sell", shares=Decimal("7"), order_type="FOK")
    kind, kwargs = client.calls[0]
    assert kind == "market"
    assert kwargs["shares"] == "7" and isinstance(kwargs["shares"], str)
    assert "amount" not in kwargs
    assert kwargs["order_type"] == "FOK"


@pytest.mark.parametrize("amount", ["0", "-5"])
def test_market_buy_rejects_non_positive_amount(amount):
    client = _CaptureClient()
    with pytest.raises(ValueError):
        orders.build_signed_market_order(client, token_id=1, side="buy", amount=amount)


def test_market_buy_max_spend_must_be_positive():
    client = _CaptureClient()
    with pytest.raises(ValueError):
        orders.build_signed_market_order(client, token_id=1, side="buy", amount="2", max_spend="0")


def test_market_buy_max_spend_serializes_string():
    client = _CaptureClient()
    orders.build_signed_market_order(client, token_id=1, side="buy", amount="2", max_spend=Decimal("3"))
    _, kwargs = client.calls[0]
    assert kwargs["max_spend"] == "3" and isinstance(kwargs["max_spend"], str)
