# poly/trade.py
"""Order-flow orchestration: build plan → preview → (dry-run/confirm) → submit.

Ported from the old poly/cli.py (commit 2979939). Safety rules are preserved
verbatim: 0<price<1 validation; round_to_tick then re-validate (reject if rounds
to 0/1); side-aware market mapping (BUY→amount+max_spend; SELL→shares); string
serialization to the SDK; dry-run never posts; typed-YES confirm; approvals retry
on InsufficientAllowanceError.
"""

from dataclasses import dataclass
from decimal import Decimal

from . import orders
from .market import resolve_target, live_price
from .output import emit

try:
    from polymarket import InsufficientAllowanceError
except Exception:  # pragma: no cover - defensive
    InsufficientAllowanceError = ()


@dataclass(frozen=True)
class OrderPlan:
    kind: str            # "limit" | "market"
    side: str
    token_id: str
    order_type: str
    price: Decimal | None = None
    size: Decimal | None = None
    amount: str | None = None
    shares: str | None = None
    max_spend: str | None = None
    requested_price: Decimal | None = None
    tick_assumed: bool = False


def _market_plan(side, target, usd, size, order_type, max_spend) -> OrderPlan:
    """Market orders: BUY spends USD (amount), SELL delivers shares.

    The SDK rejects BUY+shares and SELL+amount, so we map by side, not by which
    flag the user passed, and refuse the wrong combination up front.
    """
    ot = (order_type or "FAK").upper()
    if side == "BUY":
        if usd is None:
            raise SystemExit("A market BUY needs --usd (USD to spend); --size is for market SELL.")
        return OrderPlan("market", side, target.token_id, ot, amount=usd, max_spend=(max_spend or usd))
    # SELL
    if size is None:
        raise SystemExit("A market SELL needs --size (shares to sell); --usd is for market BUY.")
    return OrderPlan("market", side, target.token_id, ot, shares=size)


def _limit_plan(side, target, usd, size, price, order_type) -> OrderPlan:
    order_type_str = (order_type or "GTC").upper()
    if order_type_str != "GTC":
        raise SystemExit("Limit orders only support --order-type GTC. Use --market for FAK/FOK.")
    if not price:
        raise SystemExit("--price is required for limit orders (or use --market).")

    requested = orders.validate_price(price)
    p = orders.round_to_tick(requested, target.tick_size)
    try:
        orders.validate_price(p)
    except ValueError:
        tick = orders.decimal_str(target.tick_size) if target.tick_size else "0.01"
        raise SystemExit(
            f"--price {orders.decimal_str(requested)} rounds to {orders.decimal_str(p)} "
            f"at tick {tick}, which is not tradable (must be strictly between 0 and 1)."
        )
    sz_raw = orders.compute_size_from_usd(usd, p) if usd is not None else orders.validate_size(size)
    # Normalize trailing zeros so Decimal("2.00") becomes Decimal("2") for clean display.
    sz = orders.to_decimal(orders.decimal_str(sz_raw))
    return OrderPlan(
        "limit", side, target.token_id, "GTC",
        price=p, size=sz,
        requested_price=requested,
        tick_assumed=target.tick_size is None,
    )


def build_plan(*, side, market_order, token_id=None, slug=None, url=None, outcome="yes",
               usd=None, size=None, price=None, order_type=None, max_spend=None, pub):
    """Resolve the target and build an OrderPlan (pure; no SDK calls except public reads)."""
    target = resolve_target(pub, token_id=token_id, slug=slug, url=url, outcome=outcome)
    if market_order:
        plan = _market_plan(side, target, usd, size, order_type, max_spend)
    else:
        plan = _limit_plan(side, target, usd, size, price, order_type)
    return target, plan


# --------------------------------------------------------------------------- #
# Output helpers (return dicts for emit() rather than print())
# --------------------------------------------------------------------------- #

def _wallet_str(client) -> str:
    for attr in ("wallet", "wallet_address", "address", "account_address"):
        value = getattr(client, attr, None)
        if value:
            return str(value)
    return "(unknown)"


def _fmt(value) -> str:
    return orders.decimal_str(value) if isinstance(value, Decimal) else str(value)


def _preview_dict(target, plan: OrderPlan, client, book) -> dict:
    """Build the order preview as a plain dict for emit()."""
    d: dict = {}
    if target.question:
        d["market"] = target.question
    if target.outcome_label:
        d["outcome"] = target.outcome_label
    if target.condition_id:
        d["condition"] = target.condition_id
    d["side"] = plan.side
    d["token_id"] = plan.token_id
    d["wallet"] = _wallet_str(client)

    if plan.kind == "limit":
        d["order"] = "limit / GTC"
        d["price"] = f"{_fmt(plan.price)} USDC/share"
        d["size"] = f"{_fmt(plan.size)} shares"
        notional = plan.price * plan.size
        d["~notional"] = f"{orders.decimal_str(notional.quantize(Decimal('0.0001')))} USDC"
        if plan.requested_price is not None and plan.requested_price != plan.price:
            tick = _fmt(target.tick_size) if target.tick_size else "0.01"
            d["note_tick"] = (
                f"price adjusted {_fmt(plan.requested_price)} -> {_fmt(plan.price)} (tick {tick})"
            )
        if plan.tick_assumed:
            d["note_assumed"] = "tick size unknown for this token; assumed 0.01"
    else:
        d["order"] = f"market / {plan.order_type}"
        if plan.side == "BUY":
            d["spend"] = f"{plan.amount} USDC (market BUY)"
            if plan.max_spend:
                d["max_spend"] = f"{plan.max_spend} USDC (fee-inclusive cap)"
        else:
            d["shares"] = f"{plan.shares} (market SELL)"
            if book is not None:
                est = book * orders.to_decimal(plan.shares)
                d["~proceeds"] = f"~{orders.decimal_str(est.quantize(Decimal('0.01')))} USDC (est.)"

    if book is not None:
        d["book_price"] = f"{orders.decimal_str(book)} ({plan.side})"
    else:
        d["book_price"] = "unavailable"
    return d


def _signed_dict(client, signed) -> dict:
    """Build the signed-identity dict (dry-run output) for emit()."""
    d: dict = {"dry_run": True}
    for attr in (
        "maker", "signer", "token_id", "side", "maker_amount", "taker_amount",
        "order_type", "signature_type", "expiration",
    ):
        value = getattr(signed, attr, None)
        if value is not None:
            d[attr] = value
    d["wallet"] = _wallet_str(client)
    return d


# --------------------------------------------------------------------------- #
# Signing + submission
# --------------------------------------------------------------------------- #

def _build_signed(client, plan: OrderPlan):
    """Build (sign) an order without posting. Shared by dry-run and live paths."""
    if plan.kind == "limit":
        return orders.build_signed_limit_order(
            client, token_id=plan.token_id, price=plan.price,
            size=plan.size, side=plan.side,
        )
    return orders.build_signed_market_order(
        client, token_id=plan.token_id, side=plan.side,
        amount=plan.amount, shares=plan.shares,
        max_spend=plan.max_spend, order_type=plan.order_type,
    )


def _confirm(prompt: str) -> bool:
    """Typed-YES confirmation; non-interactive input (EOFError) never auto-submits."""
    try:
        return input(prompt).strip() == "YES"
    except EOFError:
        return False


def _submit(client, signed) -> object:
    """Post a signed order, with a one-time approvals-retry on InsufficientAllowanceError."""
    try:
        return orders.post_signed_order(client, signed)
    except Exception as exc:  # noqa: BLE001
        if InsufficientAllowanceError and isinstance(exc, InsufficientAllowanceError):
            emit("table", {"allowance_error": str(exc)})
            if _confirm('Run setup_trading_approvals()? This submits an ON-CHAIN transaction. Type "YES": '):
                client.setup_trading_approvals()
                return orders.post_signed_order(client, signed)
            raise SystemExit("Aborted: approvals not set up.")
        raise


def run(ctx, *, pub, secure_factory, target, plan: OrderPlan, dry_run: bool, yes: bool) -> int:
    """Emit preview; dry-run emits signed identity & returns 0 without posting;
    else confirm + submit; returns exit code 0/1."""
    fmt = getattr(ctx.obj, "output", "table")
    client = secure_factory()
    book = live_price(pub, plan.token_id, plan.side)
    emit(fmt, _preview_dict(target, plan, client, book))

    signed = _build_signed(client, plan)

    if dry_run:
        emit(fmt, _signed_dict(client, signed))
        return 0

    if not yes and not _confirm('\nType "YES" to submit this order: '):
        emit(fmt, {"aborted": True})
        return 1

    resp = _submit(client, signed)
    emit(fmt, {"result": orders.describe_response(resp)})
    return 0 if orders.is_accepted(resp) else 1
