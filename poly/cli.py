"""Command-line entry point: ``poly buy`` / ``poly sell``.

Flow per command: resolve the trade target, build the order plan, sign it
locally, show a preview, then (unless ``--dry-run``) confirm and submit. Order
construction and submission are split so ``--dry-run`` and the real path share
exactly the same signing code.
"""

import argparse
import re
import sys
from dataclasses import replace
from decimal import Decimal

from . import orders
from .config import build_public_client, build_secure_client, load_settings
from .market import ResolvedTarget, live_price, resolve_target

try:  # optional: only used to detect the missing-approvals case
    from polymarket import InsufficientAllowanceError
except Exception:  # pragma: no cover - defensive
    InsufficientAllowanceError = ()

try:  # SDK errors are rooted here, NOT at ValueError; we surface them friendly
    from polymarket import PolymarketError
except Exception:  # pragma: no cover - defensive
    PolymarketError = None

_FRIENDLY_ERRORS = (ValueError,) + ((PolymarketError,) if PolymarketError else ())
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="poly", description="Place buy/sell orders on Polymarket."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("buy", "sell"):
        cmd = sub.add_parser(name, help=f"{name.capitalize()} an outcome.")
        _add_order_args(cmd)
        cmd.set_defaults(side=name.upper())
    return parser


def _add_order_args(cmd: argparse.ArgumentParser) -> None:
    target = cmd.add_mutually_exclusive_group(required=True)
    target.add_argument("--token-id", "--token", dest="token_id", help="CLOB token id.")
    target.add_argument("--slug", help="Market slug.")
    target.add_argument("--url", help="Market URL.")
    cmd.add_argument(
        "--outcome", choices=["yes", "no"], default="yes",
        help="Outcome side (default yes); ignored with --token-id.",
    )

    size = cmd.add_mutually_exclusive_group(required=True)
    size.add_argument("--usd", help="USD to spend (limit: size = usd / price; market BUY: amount).")
    size.add_argument("--size", help="Shares to trade (limit, or market SELL).")

    cmd.add_argument("--price", help="Limit price per share, 0-1. Required unless --market.")
    cmd.add_argument("--market", action="store_true", help="Market order instead of limit.")
    cmd.add_argument("--order-type", dest="order_type", help="GTC (limit) or FAK/FOK (market).")
    cmd.add_argument("--max-spend", dest="max_spend", help="Market BUY fee-inclusive USD cap (default: --usd).")
    cmd.add_argument("--wallet", help="Override the account wallet for this run.")
    cmd.add_argument("--dry-run", action="store_true", help="Build/sign only; do not submit.")
    cmd.add_argument("--yes", action="store_true", help="Skip the typed-YES confirmation.")


# --------------------------------------------------------------------------- #
# Order planning (pure; depends only on validated args + resolved target)
# --------------------------------------------------------------------------- #

def _resolve_order_plan(args, target: ResolvedTarget) -> dict:
    return _market_plan(args, target) if args.market else _limit_plan(args, target)


def _market_plan(args, target: ResolvedTarget) -> dict:
    """Market orders: BUY spends USD (amount), SELL delivers shares.

    The SDK rejects BUY+shares and SELL+amount, so we map by side, not by which
    flag the user happened to pass, and refuse the wrong combination up front.
    """
    if args.price:
        raise SystemExit("--price is not used with --market orders.")
    order_type = (args.order_type or "FAK").upper()
    plan = {
        "kind": "market",
        "side": args.side,
        "token_id": target.token_id,
        "order_type": order_type,
    }
    if args.side == "BUY":
        if args.usd is None:
            raise SystemExit("A market BUY needs --usd (USD to spend); --size is for market SELL.")
        plan["amount"] = args.usd
        # Cap total (incl. fees) so a market BUY never spends more than intended.
        plan["max_spend"] = args.max_spend if args.max_spend is not None else args.usd
    else:  # SELL
        if args.size is None:
            raise SystemExit("A market SELL needs --size (shares to sell); --usd is for market BUY.")
        plan["shares"] = args.size
    return plan


def _limit_plan(args, target: ResolvedTarget) -> dict:
    order_type = (args.order_type or "GTC").upper()
    if order_type != "GTC":
        raise SystemExit(
            "Limit orders only support --order-type GTC. Use --market for FAK/FOK."
        )
    if not args.price:
        raise SystemExit("--price is required for limit orders (or use --market).")

    requested_price = orders.validate_price(args.price)
    price = orders.round_to_tick(requested_price, target.tick_size)
    try:
        orders.validate_price(price)
    except ValueError:
        tick = orders.decimal_str(target.tick_size) if target.tick_size else "0.01"
        raise SystemExit(
            f"--price {orders.decimal_str(requested_price)} rounds to {orders.decimal_str(price)} "
            f"at tick {tick}, which is not tradable (must be strictly between 0 and 1)."
        )
    size = (
        orders.compute_size_from_usd(args.usd, price)
        if args.usd is not None
        else orders.validate_size(args.size)
    )
    return {
        "kind": "limit",
        "side": args.side,
        "token_id": target.token_id,
        "price": price,
        "size": size,
        "requested_price": requested_price,
        "tick_assumed": target.tick_size is None,
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def _wallet_str(client) -> str:
    for attr in ("wallet", "wallet_address", "address", "account_address"):
        value = getattr(client, attr, None)
        if value:
            return str(value)
    return "(unknown)"


def _fmt(value) -> str:
    return orders.decimal_str(value) if isinstance(value, Decimal) else str(value)


def _print_preview(target: ResolvedTarget, plan: dict, client, book) -> None:
    print("=" * 64)
    print("About to place this order:")
    if target.question:
        print(f"  market    : {target.question}")
    if target.outcome_label:
        print(f"  outcome   : {target.outcome_label}")
    if target.condition_id:
        print(f"  condition : {target.condition_id}")
    print(f"  side      : {plan['side']}")
    print(f"  token id  : {plan['token_id']}")
    print(f"  wallet    : {_wallet_str(client)}")

    if plan["kind"] == "limit":
        print("  order     : limit / GTC")
        print(f"  price     : {_fmt(plan['price'])} USDC/share")
        print(f"  size      : {_fmt(plan['size'])} shares")
        notional = plan["price"] * plan["size"]
        print(f"  ~notional : {orders.decimal_str(notional.quantize(Decimal('0.0001')))} USDC")
        if plan.get("requested_price") is not None and plan["requested_price"] != plan["price"]:
            tick = _fmt(target.tick_size) if target.tick_size else "0.01"
            print(f"  note      : price adjusted {_fmt(plan['requested_price'])} -> {_fmt(plan['price'])} (tick {tick})")
        if plan.get("tick_assumed"):
            print("  note      : tick size unknown for this token; assumed 0.01")
    else:
        print(f"  order     : market / {plan['order_type']}")
        if plan["side"] == "BUY":
            print(f"  spend     : {plan['amount']} USDC (market BUY)")
            if plan.get("max_spend"):
                print(f"  max spend : {plan['max_spend']} USDC (fee-inclusive cap)")
        else:
            print(f"  shares    : {plan['shares']} (market SELL)")
            if book is not None:
                est = book * orders.to_decimal(plan["shares"])
                print(f"  ~proceeds : ~{orders.decimal_str(est.quantize(Decimal('0.01')))} USDC (est.)")

    print(f"  book price: {orders.decimal_str(book)} ({plan['side']})" if book is not None
          else "  book price: unavailable")
    print("=" * 64)


def _print_signed_identity(client, signed) -> None:
    print("\nSigned order (built locally, NOT submitted):")
    for attr in (
        "maker", "signer", "token_id", "side", "maker_amount", "taker_amount",
        "order_type", "signature_type", "expiration",
    ):
        value = getattr(signed, attr, None)
        if value is not None:
            print(f"  {attr:14}: {value}")
    print(f"  {'wallet':14}: {_wallet_str(client)}")


# --------------------------------------------------------------------------- #
# Submission
# --------------------------------------------------------------------------- #

def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip() == "YES"
    except EOFError:  # non-interactive / piped input never auto-submits
        return False


def _submit(client, signed) -> object:
    """Post a signed order, handling a one-time approvals retry."""
    try:
        return orders.post_signed_order(client, signed)
    except Exception as exc:  # noqa: BLE001 - re-raised unless it's the approvals case
        if InsufficientAllowanceError and isinstance(exc, InsufficientAllowanceError):
            print(f"\nThis wallet is missing trading approvals: {exc}")
            if _confirm('Run setup_trading_approvals()? This submits an ON-CHAIN transaction. Type "YES": '):
                client.setup_trading_approvals()
                return orders.post_signed_order(client, signed)
            raise SystemExit("Aborted: approvals not set up.")
        raise


def _build_signed(client, plan: dict):
    if plan["kind"] == "limit":
        return orders.build_signed_limit_order(
            client, token_id=plan["token_id"], price=plan["price"],
            size=plan["size"], side=plan["side"],
        )
    return orders.build_signed_market_order(
        client, token_id=plan["token_id"], side=plan["side"],
        amount=plan.get("amount"), shares=plan.get("shares"),
        max_spend=plan.get("max_spend"), order_type=plan["order_type"],
    )


def run_order(args, *, public_client=None, make_secure_client=None) -> int:
    """Resolve, preview, and (unless dry-run) submit one order. Returns exit code."""
    if args.wallet and not _ADDRESS_RE.match(args.wallet):
        raise SystemExit(
            f"--wallet must be a 0x-prefixed 40-hex-character address, got {args.wallet!r}"
        )

    pub = public_client or build_public_client()
    target = resolve_target(
        pub, token_id=args.token_id, slug=args.slug, url=args.url, outcome=args.outcome
    )
    plan = _resolve_order_plan(args, target)

    if make_secure_client is None:
        settings = load_settings()
        if args.wallet:
            settings = replace(settings, wallet_address=args.wallet)
        client = build_secure_client(settings)
    else:
        client = make_secure_client()

    book = live_price(pub, target.token_id, plan["side"])
    _print_preview(target, plan, client, book)
    if args.wallet:
        print("NOTE: trading from an overridden --wallet, not the default deposit wallet.")

    signed = _build_signed(client, plan)

    if args.dry_run:
        _print_signed_identity(client, signed)
        print("\nDry run — nothing was submitted.")
        return 0

    if not args.yes and not _confirm('\nType "YES" to submit this order: '):
        print("Aborted.")
        return 1

    response = _submit(client, signed)
    print("\n" + orders.describe_response(response))
    return 0 if orders.is_accepted(response) else 1


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_order(args)
    except _FRIENDLY_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
