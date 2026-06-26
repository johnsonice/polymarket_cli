# poly

A tiny CLI for placing **buy/sell orders** on Polymarket from your deposit wallet.

Built on the official unified **`polymarket-client`** SDK (`Polymarket/py-sdk`) —
*not* the legacy `py-clob-client-v2`, which cannot post orders from deposit wallets
(signature type 3 / POLY_1271) and corrupts clean prices via float drift. See
[`docs/superpowers/specs/2026-06-25-poly-cli-design.md`](docs/superpowers/specs/2026-06-25-poly-cli-design.md)
for the full design and the list of SDK bugs this tool sidesteps.

## Setup

```bash
uv sync --extra dev          # create .venv and install deps (SDK is a prerelease)
cp .env.example .env         # then put your signer private key in .env
```

`.env` only needs your signer key — the SDK derives your deposit wallet from it:

```
POLYMARKET_PRIVATE_KEY=0x...
```

## Usage

```bash
# Always dry-run first: builds + signs locally, prints the order + your resolved
# wallet, and DOES NOT submit. Confirm the wallet matches polymarket.com/settings.
uv run poly buy --slug <market-slug> --outcome yes --usd 1 --price 0.50 --dry-run

# Buy $1 of YES at a 0.50 limit (size = usd / price). Asks you to type YES.
uv run poly buy --slug <market-slug> --outcome yes --usd 1 --price 0.50

# Sell 10 shares of NO at a 0.40 limit, no prompt.
uv run poly sell --slug <market-slug> --outcome no --size 10 --price 0.40 --yes

# Trade a token id directly (e.g. copied from the site).
uv run poly buy --token-id 1234567... --usd 2 --price 0.65

# Market BUY: spends USD, capped so fees never push you past it.
uv run poly buy --url https://polymarket.com/event/... --outcome yes --usd 2 --market
# Market SELL: delivers shares.
uv run poly sell --slug <market-slug> --outcome no --size 10 --market
```

### Flags

| Flag | Meaning |
|---|---|
| `--token-id` / `--slug` / `--url` | What to trade (one of). With slug/url, use `--outcome`. |
| `--outcome yes\|no` | Which side of the market (default `yes`). Ignored with `--token-id`. |
| `--usd` / `--size` | Limit: `--usd` (size = usd/price) **or** `--size` shares. Market: **BUY needs `--usd`**, **SELL needs `--size`**. |
| `--price` | Limit price per share, strictly between 0 and 1. Required unless `--market`. Rounded to the market tick. |
| `--market` | Market order instead of a limit order. |
| `--order-type` | `GTC` (limit, default) or `FAK`/`FOK` (market). |
| `--max-spend` | Market BUY only: fee-inclusive USD cap (defaults to `--usd`, so a market BUY never spends more than you asked). |
| `--wallet` | Override the resolved deposit wallet for this run (validated 0x address). |
| `--dry-run` | Build + sign locally, print details, do **not** submit. |
| `--yes` | Skip the typed-`YES` confirmation. |

> **Market order semantics** mirror the SDK: a market **BUY** spends a USD `amount`
> (use `--usd`), a market **SELL** delivers `shares` (use `--size`). Mixing them is
> rejected up front. For a market BUY, the SDK reduces the executed amount so that
> amount + fees stays within `--max-spend`.

## Safety

Every real submit shows a preview and requires typing `YES` (unless `--yes`).
Use `--dry-run` to inspect exactly what would be sent. Prices are validated to be
between 0 and 1; sizes must be positive; amounts are rounded to whole cents and
the tick size before being sent, as strings, to avoid the SDK's float-precision
rejections.
