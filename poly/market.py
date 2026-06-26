"""Resolve a trade target (market + outcome) to a CLOB token id.

Trading needs a numeric ``token_id``. The user may give one directly, or give a
market ``slug``/``url`` plus an outcome (``yes``/``no``) which we resolve through
the public Gamma API. We also surface the tick size and best bid/ask for the
order preview, all best-effort so direct-token trading never breaks on a lookup.
"""

from dataclasses import dataclass
from decimal import Decimal

from .orders import normalize_side


@dataclass(frozen=True)
class ResolvedTarget:
    """Everything the CLI needs to build and preview an order."""

    token_id: str
    outcome_label: str | None = None
    question: str | None = None
    condition_id: str | None = None
    tick_size: Decimal | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None


def _to_decimal(value):
    return Decimal(str(value)) if value is not None else None


def _tick(market):
    trading = getattr(market, "trading", None)
    return _to_decimal(getattr(trading, "minimum_tick_size", None)) if trading else None


def _best_prices(market):
    prices = getattr(market, "prices", None)
    if prices is None:
        return None, None
    return (
        _to_decimal(getattr(prices, "best_bid", None)),
        _to_decimal(getattr(prices, "best_ask", None)),
    )


def _outcome_token(market, outcome: str):
    name = (outcome or "yes").lower()
    if name not in ("yes", "no"):
        raise SystemExit(f"--outcome must be 'yes' or 'no', got {outcome!r}")
    outcomes = getattr(market, "outcomes", None)
    chosen = getattr(outcomes, name, None) if outcomes else None
    if chosen is None or getattr(chosen, "token_id", None) is None:
        raise SystemExit(f"This market has no '{name}' outcome token id.")
    return chosen


def _match_token(market, token_id: str):
    """Find which outcome a given token id corresponds to (for labeling)."""
    outcomes = getattr(market, "outcomes", None)
    for name in ("yes", "no"):
        outcome = getattr(outcomes, name, None) if outcomes else None
        if outcome is not None and str(getattr(outcome, "token_id", "")) == str(token_id):
            return getattr(outcome, "label", name), outcome
    return None, None


def _market_for_token(pub, token_id: str):
    """Best-effort lookup of the market that contains a CLOB token id."""
    try:
        paginator = pub.list_markets(clob_token_ids=str(token_id))
        page = paginator.first_page()
        items = getattr(page, "items", None) or []
        return items[0] if items else None
    except Exception:
        return None


def _target_from_market(market, token_id, outcome_label) -> ResolvedTarget:
    best_bid, best_ask = _best_prices(market)
    return ResolvedTarget(
        token_id=str(token_id),
        outcome_label=outcome_label,
        question=getattr(market, "question", None),
        condition_id=getattr(market, "condition_id", None),
        tick_size=_tick(market),
        best_bid=best_bid,
        best_ask=best_ask,
    )


def resolve_target(pub, *, token_id=None, slug=None, url=None, outcome="yes") -> ResolvedTarget:
    """Resolve exactly one of token_id / slug / url into a ``ResolvedTarget``."""
    provided = [value for value in (token_id, slug, url) if value]
    if len(provided) != 1:
        raise SystemExit("Specify exactly one of --token-id, --slug, or --url.")

    if token_id:
        market = _market_for_token(pub, token_id)
        if market is None:
            return ResolvedTarget(token_id=str(token_id))
        label, _ = _match_token(market, token_id)
        return _target_from_market(market, token_id, label)

    try:
        market = pub.get_market(slug=slug) if slug else pub.get_market(url=url)
    except Exception as exc:
        ref = f"slug={slug!r}" if slug else f"url={url!r}"
        raise SystemExit(f"Could not find market ({ref}): {exc}")

    chosen = _outcome_token(market, outcome)
    token = str(chosen.token_id)
    if not token.isdigit():
        raise SystemExit(
            f"Resolved an unexpected token id from the market ({token!r}); refusing to trade."
        )
    return _target_from_market(market, token, getattr(chosen, "label", outcome))


def live_price(pub, token_id: str, side: str):
    """Best-effort current price for a token/side; ``None`` on any failure."""
    try:
        return pub.get_price(token_id=str(token_id), side=normalize_side(side))
    except Exception:
        return None
