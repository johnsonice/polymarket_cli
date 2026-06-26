"""Order validation, sizing, and submission.

All numeric work is done with ``decimal.Decimal`` and handed to the SDK as
**strings**. This is deliberate: the legacy client corrupted clean prices like
``0.51`` into ``0.5100011...`` through float arithmetic and the CLOB rejected
them (issues #59/#66/#68). Passing exact decimal strings avoids that entirely.
"""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

MIN_PRICE = Decimal("0")
MAX_PRICE = Decimal("1")
DEFAULT_TICK = Decimal("0.01")
ALLOWED_TICKS = {Decimal("0.1"), Decimal("0.01"), Decimal("0.001"), Decimal("0.0001")}
DEFAULT_SIZE_DECIMALS = 2

LIMIT_ORDER_TYPE = "GTC"
MARKET_ORDER_TYPES = ("FAK", "FOK")


def to_decimal(value, name: str = "value") -> Decimal:
    """Parse a value into a Decimal via its string form (never via float)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def normalize_side(side: str) -> str:
    """Map any-case 'buy'/'sell' to the SDK's 'BUY'/'SELL' literals."""
    normalized = str(side).upper()
    if normalized in ("BUY", "SELL"):
        return normalized
    raise ValueError(f"side must be BUY or SELL, got {side!r}")


def normalize_tick(tick) -> Decimal:
    """Return a supported tick size, defaulting to 0.01 for unknown values."""
    if tick is None:
        return DEFAULT_TICK
    value = to_decimal(tick, "tick")
    return value if value in ALLOWED_TICKS else DEFAULT_TICK


def validate_price(price) -> Decimal:
    """Validate a per-share price is strictly between 0 and 1."""
    value = to_decimal(price, "price")
    if not (MIN_PRICE < value < MAX_PRICE):
        raise ValueError(f"price must be strictly between 0 and 1, got {value}")
    return value


def validate_size(size) -> Decimal:
    """Validate a share size is strictly positive."""
    value = to_decimal(size, "size")
    if value <= 0:
        raise ValueError(f"size must be positive, got {value}")
    return value


def round_to_tick(price, tick=DEFAULT_TICK) -> Decimal:
    """Round a price to the nearest multiple of the market tick size."""
    value = to_decimal(price, "price")
    step = normalize_tick(tick)
    steps = (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return steps * step


def compute_size_from_usd(usd, price, size_decimals: int = DEFAULT_SIZE_DECIMALS) -> Decimal:
    """Convert a USD spend into a share size: ``size = floor(usd / price)``.

    Rounds the size DOWN so the order never spends more than the requested USD.
    """
    amount = to_decimal(usd, "usd")
    if amount <= 0:
        raise ValueError(f"usd must be positive, got {amount}")
    unit_price = validate_price(price)
    quantum = Decimal(1).scaleb(-size_decimals)
    return (amount / unit_price).quantize(quantum, rounding=ROUND_DOWN)


def decimal_str(value) -> str:
    """Format a Decimal as a plain (non-exponent) string with no trailing zeros."""
    value = value if isinstance(value, Decimal) else to_decimal(value)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def is_accepted(response) -> bool:
    """True when the CLOB accepted the order (``AcceptedOrder.ok``)."""
    return bool(getattr(response, "ok", False))


def describe_response(response) -> str:
    """Human-readable summary of an AcceptedOrder / RejectedOrder."""
    if is_accepted(response):
        order_id = getattr(response, "order_id", "?")
        status = getattr(response, "status", "?")
        return f"ACCEPTED  order_id={order_id}  status={status}"
    code = getattr(response, "code", "?")
    message = getattr(response, "message", "?")
    return f"REJECTED  code={code}  message={message}"


def build_signed_limit_order(client, *, token_id: str, price, size, side: str):
    """Validate inputs and build (sign) a limit order WITHOUT posting it."""
    unit_price = validate_price(price)
    share_size = validate_size(size)
    order_side = normalize_side(side)
    return client.create_limit_order(
        token_id=str(token_id),
        price=decimal_str(unit_price),
        size=decimal_str(share_size),
        side=order_side,
    )


def build_signed_market_order(
    client,
    *,
    token_id: str,
    side: str,
    amount=None,
    shares=None,
    max_spend=None,
    order_type: str = "FAK",
):
    """Validate inputs and build (sign) a market order WITHOUT posting it."""
    kwargs = _market_kwargs(
        token_id=token_id,
        side=side,
        amount=amount,
        shares=shares,
        max_spend=max_spend,
        order_type=order_type,
    )
    return client.create_market_order(**kwargs)


def post_signed_order(client, signed_order):
    """Submit an already-signed order. Returns AcceptedOrder | RejectedOrder."""
    return client.post_order(signed_order)


def place_market_order(
    client,
    *,
    token_id: str,
    side: str,
    amount=None,
    shares=None,
    max_spend=None,
    order_type: str = "FAK",
):
    """Build and submit a market order in one step."""
    kwargs = _market_kwargs(
        token_id=token_id,
        side=side,
        amount=amount,
        shares=shares,
        max_spend=max_spend,
        order_type=order_type,
    )
    return client.place_market_order(**kwargs)


def _market_kwargs(*, token_id, side, amount, shares, max_spend, order_type) -> dict:
    """Assemble validated keyword args for a market order call.

    The SDK enforces strict side semantics: a market BUY takes ``amount`` (USD)
    and a market SELL takes ``shares``. We validate that here so the user gets a
    clear error instead of an SDK rejection deep in the stack.
    """
    if order_type not in MARKET_ORDER_TYPES:
        raise ValueError(
            f"market order_type must be one of {MARKET_ORDER_TYPES}, got {order_type!r}"
        )
    order_side = normalize_side(side)
    if (amount is None) == (shares is None):
        raise ValueError("market order requires exactly one of amount (USD) or shares")
    if order_side == "BUY" and shares is not None:
        raise ValueError("market BUY uses amount (USD to spend), not shares")
    if order_side == "SELL" and amount is not None:
        raise ValueError("market SELL uses shares, not amount (USD)")

    kwargs = {
        "token_id": str(token_id),
        "side": order_side,
        "order_type": order_type,
    }
    if amount is not None:
        usd = to_decimal(amount, "amount")
        if usd <= 0:
            raise ValueError(f"amount must be positive, got {usd}")
        kwargs["amount"] = decimal_str(usd)
    if shares is not None:
        kwargs["shares"] = decimal_str(validate_size(shares))
    if max_spend is not None:
        spend = to_decimal(max_spend, "max_spend")
        if spend <= 0:
            raise ValueError(f"max_spend must be positive, got {spend}")
        kwargs["max_spend"] = decimal_str(spend)
    return kwargs
