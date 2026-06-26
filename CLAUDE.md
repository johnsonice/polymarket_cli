# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`poly` is a small CLI for placing buy/sell orders on Polymarket from a deposit wallet. It is a focused
project — four source modules in `poly/` (~720 lines) with a mirror test module each.

## Commands

Use **`uv`** for everything. The project requires **Python ≥3.11**, but the system `python3` here is 3.9 —
running `python3 -m pytest` or `pytest` directly will fail. `uv run` selects the right interpreter and venv.

```bash
uv sync --extra dev          # create .venv + install deps (SDK is a prerelease; allowed via [tool.uv])
cp .env.example .env         # then set POLYMARKET_PRIVATE_KEY=0x...

uv run poly buy --slug <market-slug> --outcome yes --usd 1 --price 0.50 --dry-run   # never submits
uv run pytest                # all tests (testpaths = ["tests"])
uv run pytest tests/test_orders.py::test_decimal_str_strips_trailing_zeros   # single test
uv run pytest --cov=poly --cov-report=term-missing                           # coverage
```

There is **no configured linter/formatter** in `pyproject.toml` (no ruff/black config). Don't invent a lint
command; tests are the gate.

## The core invariant: Decimal in, strings out

This project exists to sidestep bugs in the legacy `py-clob-client-v2`. The single most important rule,
which every numeric path depends on:

> **All prices/sizes are computed with `decimal.Decimal` and handed to the SDK as strings — never floats.**

Passing floats let the legacy client corrupt clean prices (`0.51` → `0.5100011…`) and the CLOB rejected them
(issues #59/#66/#68). `poly/orders.py` is the chokepoint: `to_decimal()` parses via `str()` (never `float()`),
and `build_signed_*` / `_market_kwargs` emit `decimal_str(...)`. **Any new numeric code must keep values as
`Decimal` and serialize with `decimal_str` before the SDK boundary.** Breaking this reintroduces the exact bug
the tool was built to avoid.

## SDK and wallet model

- Built on the **official unified `polymarket-client` SDK** (`Polymarket/py-sdk`, prerelease `0.1.0b9`),
  imported as `from polymarket import ...` — **not** the legacy `py-clob-client-v2`.
- `PublicClient()` for unauthenticated market reads; `SecureClient.create(private_key=, wallet=, api_key=)`
  for signing/submitting. Both are imported **lazily** inside `poly/config.py` so pure-logic tests don't pay
  the SDK import cost.
- Auth is a single signer private key. The SDK **derives the deposit wallet** (signature type 3 / POLY_1271)
  deterministically from it — this type-3 path is what the legacy client could not post. `POLYMARKET_WALLET_ADDRESS`
  only overrides the wallet (Safe/Proxy/EOA); relayer creds in `.env` are only needed for on-chain
  deployment/approvals.

## Architecture (data flow per command)

`poly/cli.py` `run_order()` is the orchestrator; the flow is:

**resolve target → plan order (pure) → build secure client → preview → sign → confirm → submit**

| Module | Responsibility |
|---|---|
| `poly/market.py` | `resolve_target()` maps one of `--token-id` / `--slug` / `--url` (+ `--outcome`) to a frozen `ResolvedTarget` (token_id, tick_size, best bid/ask, question, condition_id) via the public Gamma API. **Best-effort**: every lookup is wrapped so failures return `None`/partial data and never block direct `--token-id` trading. `live_price()` is likewise swallow-on-error. |
| `poly/orders.py` | All validation, sizing, tick rounding, and the Decimal→string serialization. `build_signed_limit_order` / `build_signed_market_order` **sign without posting**; `post_signed_order` submits separately. Enforces SDK market-order semantics up front: BUY takes `amount` (USD), SELL takes `shares` — mixing is rejected before the SDK sees it. |
| `poly/config.py` | `Settings` (frozen dataclass; **secret fields use `field(repr=False)`** so a stray print/traceback never leaks the key), `load_settings()` (injectable `env` for tests), and the two client builders. |
| `poly/cli.py` | argparse `buy`/`sell`; `_resolve_order_plan` is pure (args + target → plan dict). `_build_signed` and `_submit` are split so **`--dry-run` and the real submit share the identical signing code** — dry-run just stops before `_submit`. SDK errors root at `PolymarketError`, not `ValueError`; both are surfaced as friendly messages. `InsufficientAllowanceError` triggers a one-time, user-confirmed on-chain `setup_trading_approvals()` retry. |

### Two design points to preserve when editing

- **Don't duplicate signing logic.** `_build_signed` is the only place orders are constructed; dry-run and
  live submission both go through it. Keep build and submit separate.
- **Keep secrets out of `repr`.** When adding a secret to `Settings`, mark it `field(repr=False)` like
  `private_key` and `relayer_api_key`.

## Testing approach

Tests are network-free and never touch the real SDK client. `run_order(args, *, public_client=, make_secure_client=)`
exposes injection seams; tests pass `FakePub` and `SimpleNamespace` stand-ins. Note the real `SignedOrder` has
**no `price`/`size` attributes** — it uses `maker_amount`/`taker_amount`; test fakes mirror that shape, so don't
assert on `price`/`size` of a signed order.

## Reference

Full design rationale and the list of legacy-SDK bugs this tool sidesteps:
[`docs/superpowers/specs/2026-06-25-poly-cli-design.md`](docs/superpowers/specs/2026-06-25-poly-cli-design.md).
This is a git repo (`main`); commit here, not at the `Side_Projects/` workspace root.
