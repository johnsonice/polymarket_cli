# `poly` — Polymarket trading CLI — Design Spec

**Date:** 2026-06-25
**Status:** Approved (design); ready for implementation planning
**Location:** `Poly_API/` (the `reference/` docs are left untouched)

---

## 1. Purpose

A small, focused command-line tool to place **buy/sell orders** on Polymarket from
the user's own deposit wallet. Scope is deliberately narrow (YAGNI): just trading.
No separate market-discovery, balance, or positions commands — though placing an
order necessarily resolves a market and previews the live price.

## 2. Background & key decision: which SDK

Polymarket has **two** Python SDKs:

| SDK | Verdict |
|---|---|
| `py-clob-client-v2` 1.0.1 (in `reference/` quickstart + the old `polymarket-v2/` project) | **Rejected.** Cannot post type-3 deposit-wallet orders — its L1 auth binds the API key to the EOA, so the CLOB rejects every order with *"the order signer address has to be the address of the API KEY"* (open-issue cluster #49–#91). Also has float-precision bugs that corrupt clean prices (#59/#66/#68). |
| `polymarket-client` 0.1.0b9 (repo `Polymarket/py-sdk`, import `polymarket`) | **Chosen.** New official unified SDK. Trades from the deterministic deposit wallet by default, `Decimal`/string-safe prices, idempotent approvals, structured responses. Beta, but the only path that trades from the user's real wallet. |

This was confirmed by GitHub issue threads (maintainer + multiple users migrating) and
by live introspection of the installed `polymarket-client` 0.1.0b9 package.

### Bugs the design explicitly avoids (from the issue tracker)

- **Type-3 posting broken (#49–#91)** → use the new SDK, whose default account *is* the deposit wallet.
- **Float-precision rejection (#59, #66, #68)** → pass price/size to the SDK as **strings**, after rounding price to the market tick and any USD amount to whole cents.
- **SDK `print()`s errors to stdout (#36)** → read the structured `AcceptedOrder` / `RejectedOrder` return value; never scrape stdout.
- **L2 creds expire ~30 min (#40)** → construct a fresh client per CLI invocation (a CLI is short-lived anyway).
- **Market/FOK historically flakier** → default to GTC limit orders; market mode is opt-in.

## 3. Verified API surface (`polymarket-client` 0.1.0b9, sync clients)

```python
from polymarket import SecureClient, PublicClient

# Auth — default wallet = deterministic Deposit Wallet (type 3 / POLY_1271)
client = SecureClient.create(private_key=..., wallet=None)   # wallet optional override

client.setup_trading_approvals()        # idempotent; on-chain only if not already approved

# Build (sign locally) then post — enables a true dry-run preview
signed = client.create_limit_order(token_id=..., price="0.52", size="10", side="BUY",
                                   post_only=False, expiration=None, builder_code=None)
resp   = client.post_order(signed)      # -> AcceptedOrder | RejectedOrder

# Or one-shot
resp = client.place_limit_order(token_id=..., price="0.52", size="10", side="BUY")
resp = client.place_market_order(token_id=..., side="BUY", amount="10", max_spend="11",
                                 order_type="FAK")   # or shares=..., order_type="FOK"

# Responses (pydantic models)
#   AcceptedOrder: ok=True, order_id, status, making_amount, taking_amount, trade_ids, transactions_hashes
#   RejectedOrder: ok=False, code, message

# Public reads (no auth)
pub = PublicClient()
market = pub.get_market(slug=...) | pub.get_market(url=...) | pub.get_market(id=...)
#   market.condition_id, market.question, market.slug
#   market.outcomes.yes.token_id / .no.token_id  (each: label, token_id, price)
price = pub.get_price(token_id=..., side="BUY")   # -> Decimal
book  = pub.get_order_book(token_id=...)
```

Prices/sizes accept `Decimal | int | float | str`; the design always passes **strings**.

## 4. Architecture

```
Poly_API/
  reference/{auth.md, quick_start.md}     # unchanged
  pyproject.toml                          # deps + `poly` console-script entry point
  .env.example   .gitignore   README.md
  poly/
    __init__.py
    config.py    # env loading -> Settings; build sync SecureClient + PublicClient
    market.py    # resolve trade target -> token_id; fetch tick size + live price
    orders.py    # validate inputs; USD->size; tick/cent rounding; build+post orders
    cli.py       # argparse entry: `poly buy` / `poly sell`
  tests/
    test_orders.py   test_market.py   test_config.py
```

Each module has one job, communicates via plain values/dataclasses, and is unit-testable
in isolation with the SDK/network mocked.

### 4.1 `config.py`
- `@dataclass(frozen=True) Settings`: `private_key`, `wallet_address: str | None`,
  `relayer_api_key: str | None`, `relayer_api_key_address: str | None`.
- `load_settings()`: read env via `python-dotenv`; require `POLYMARKET_PRIVATE_KEY`
  (normalize `0x` prefix); `SystemExit` with a friendly message if missing.
- `build_secure_client(settings)` → `SecureClient.create(...)`; `build_public_client()` → `PublicClient()`.

### 4.2 `market.py`
- `resolve_token_id(pub, *, token_id, slug, url, outcome) -> ResolvedTarget`
  where `ResolvedTarget` carries `token_id`, `question`, `condition_id`, `outcome_label`, `tick_size`.
  - If `token_id` given → use directly (question/tick fetched best-effort for the preview).
  - Else fetch market by `slug`/`url`, pick `outcomes.yes`/`.no` by `outcome` (default `yes`).
- `live_price(pub, token_id, side) -> Decimal` for the preview (best-effort; non-fatal on error).

### 4.3 `orders.py`
- Validation: `0 < price < 1`; `size > 0`; exactly one of `--usd` / `--size`;
  `side ∈ {BUY, SELL}`; for limit orders `--price` required (mutually exclusive with `--market`).
- `compute_size(usd, price) -> Decimal` = `usd / price`; `round_to_tick(price, tick)`;
  `round_cents(amount)`. All math in `Decimal`; values handed to the SDK as **strings**.
- `build_signed_limit_order(client, ...)` → `create_limit_order(...)` (for dry-run + preview).
- `submit(client, signed | market args)` → `post_order` / `place_market_order`; returns the response.

### 4.4 `cli.py`
- `argparse` with subcommands `buy` and `sell` (a shared parent parser for common flags).
- Orchestration per command:
  1. Parse + validate args.
  2. Resolve target (`market.resolve_token_id`).
  3. Build the signed order (limit) or assemble market-order args.
  4. Print preview: question · outcome · side · price · size · ~notional · resolved wallet · live book price.
  5. `--dry-run` → print the signed-order identity (maker/wallet/side) and stop (never posts).
  6. Confirmation: require typing `YES` unless `--yes`.
  7. Pre-flight approvals: if a real post fails with an allowance/approval error (or a
     `--setup-approvals` flag is passed), call `setup_trading_approvals()` after a **separate**
     explicit confirmation (it is an on-chain action), then retry once.
  8. Post; print `order_id` + `status` (AcceptedOrder) or `code` + `message` (RejectedOrder).

## 5. CLI reference

```
poly buy   (--token-id <id> | --slug <slug> | --url <url>) [--outcome yes|no]
           (--usd <amount> | --size <shares>)  [--price <0..1> | --market]
           [--order-type GTC|FAK|FOK]  [--wallet <addr>]  [--dry-run]  [--yes]
poly sell  ...same flags...
```
- `--outcome` defaults to `yes`. Ignored when `--token-id` is given.
- `--price` required unless `--market`. `--order-type` defaults `GTC` (limit) / `FAK` (market).
- `--wallet` overrides the resolved deposit wallet for this run.

## 6. Configuration (`.env`)

```
POLYMARKET_PRIVATE_KEY=0x...            # REQUIRED — signer EOA key; derives the deposit wallet
# POLYMARKET_WALLET_ADDRESS=0x...       # optional — pin an existing wallet (deposit/safe/proxy/EOA)
# POLYMARKET_RELAYER_API_KEY=...        # optional — only if the wallet still needs deploy/approvals
# POLYMARKET_RELAYER_API_KEY_ADDRESS=0x...
```
`.gitignore` excludes `.env`. `.env.example` documents each field.

## 7. Error handling

- Boundary validation fails fast with user-facing messages (no stack traces for user error).
- SDK/network errors (`PolymarketError` subclasses: `RateLimitError`, `InsufficientAllowanceError`,
  `InsufficientLiquidityError`, `RequestRejectedError`, `TransportError`, `TimeoutError`) are caught
  and surfaced as concise messages; `InsufficientAllowanceError` triggers the approvals path (§4.4.7).
- A `RejectedOrder` is reported with its `code` + `message`, exit code non-zero.

## 8. Testing (pytest, offline)

- `test_orders.py`: price/size validation bounds; USD→size; tick rounding; cent rounding;
  side mapping; mutually-exclusive flag handling.
- `test_market.py`: target resolution for token-id / slug / url paths and yes/no selection (mocked `PublicClient`).
- `test_config.py`: settings load + missing-env errors; `0x` normalization.
- All network/SDK calls mocked; no live orders in tests. Target the repo's 80% rule on pure logic.

## 9. Safety guardrails (financial)

- Preview + typed `YES` + `--dry-run` before any submit; on-chain approvals need a separate confirm.
- Prices strictly `0 < p < 1`; amounts rounded to cents; sizes positive.
- **The author (Claude) will only ever exercise `--dry-run`.** All live submits and any
  `approve`/on-chain actions are handed back to the user to run themselves.

## 10. Implementation order (high level)

1. **Verify the path first:** scaffold project, install SDK, run a `--dry-run` and confirm the
   resolved deposit wallet == the wallet holding the user's funds (polymarket.com/settings);
   if mismatched, set `POLYMARKET_WALLET_ADDRESS`.
2. `config.py` + tests.
3. `market.py` + tests.
4. `orders.py` + tests.
5. `cli.py` wiring + a final end-to-end `--dry-run`.
6. README + `.env.example`.

## 11. Open risks

- SDK is **beta** (0.1.0b9); API may shift between releases — pin the version in `pyproject.toml`.
- The deterministic deposit wallet derived from the signer must match the funded wallet; verified
  in step 1 before any real order.
- Market orders depend on resting liquidity; thin books may partially fill or reject — limit is default.
