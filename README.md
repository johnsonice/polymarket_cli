# poly

A CLI for placing buy/sell orders on Polymarket from your deposit wallet, with group commands for reading positions and managing the local wallet.

Built on the official unified **`polymarket-client`** SDK (`Polymarket/py-sdk`) —
*not* the legacy `py-clob-client-v2`, which cannot post orders from deposit wallets
(signature type 3 / POLY_1271) and corrupts clean prices via float drift. See
[`docs/superpowers/specs/2026-06-25-poly-cli-design.md`](docs/superpowers/specs/2026-06-25-poly-cli-design.md)
for the full design and the list of SDK bugs this tool sidesteps.

## Setup

```bash
uv sync --extra dev          # create .venv and install deps (SDK is a prerelease)
```

Key management uses a config file at `~/.config/polymarket/config.json` (not `.env`).
Set up your signer key with the setup wizard:

```bash
uv run poly setup --private-key 0x...
# or: uv run poly wallet import 0x...
# or: set POLYMARKET_PRIVATE_KEY=0x... in the environment
```

**The project `.env` file is no longer read.** Key resolution order: `--private-key` flag > `POLYMARKET_PRIVATE_KEY` env > `~/.config/polymarket/config.json`.

## Command Structure

```
poly [OPTIONS] COMMAND [ARGS]...

Global options:
  -o, --output table|json    Output format (default: table)
  --private-key TEXT         Override the signer key for this run
  --signature-type INT       Signature type 0/1/2/3 (default 3 = deposit wallet)

Command groups:
  setup       Configure your signer key
  buy         Buy an outcome (alias for clob create-order / market-order)
  sell        Sell an outcome
  wallet      Manage the local key (create/import/show/address/reset)
  clob        CLOB trading and account reads
  data        On-chain portfolio data (positions, value)
```

## Usage

```bash
# Always dry-run first: builds + signs locally, prints the order, does NOT submit.
uv run poly buy --token-id <TOKEN_ID> --usd 1 --price 0.50 --dry-run

# Buy $1 of YES at a 0.50 limit. Asks you to type YES to confirm.
uv run poly buy --slug <market-slug> --outcome yes --usd 1 --price 0.50

# Sell 10 shares of NO at a 0.40 limit, skip confirmation prompt.
uv run poly sell --slug <market-slug> --outcome no --size 10 --price 0.40 --yes

# Trade a token id directly (e.g. copied from the site).
uv run poly buy --token-id 1234567... --usd 2 --price 0.65

# Market BUY: spends USD, capped so fees never push you past it.
uv run poly buy --url https://polymarket.com/event/... --outcome yes --usd 2 --market

# Market SELL: delivers shares.
uv run poly sell --slug <market-slug> --outcome no --size 10 --market

# View your open orders as JSON.
uv run poly -o json clob orders

# List positions for your wallet (resolved from config).
uv run poly -o json data positions

# List positions for any wallet address.
uv run poly -o json data positions 0x93772c4c6332901F9F5e6c3F179D623b07D7BbB7

# Show your configured wallet address.
uv run poly wallet show
```

### clob subcommands

| Command | Description |
|---|---|
| `clob create-order` | Place a limit order |
| `clob market-order` | Place a market order |
| `clob cancel ORDER_ID` | Cancel an open order |
| `clob cancel-all` | Cancel all open orders (requires typed YES) |
| `clob orders` | List open orders |
| `clob order ORDER_ID` | Get a single order |
| `clob trades` | List account trades |
| `clob balance` | Get balance/allowance |

### Flags (buy / sell / clob create-order)

| Flag | Meaning |
|---|---|
| `--token-id` / `--slug` / `--url` | What to trade (one of). With slug/url, use `--outcome`. |
| `--outcome yes\|no` | Which side of the market (default `yes`). Ignored with `--token-id`. |
| `--usd` / `--size` | Limit: `--usd` (size = usd/price) **or** `--size` shares. Market: **BUY needs `--usd`**, **SELL needs `--size`**. |
| `--price` | Limit price per share, strictly between 0 and 1. Required unless `--market`. Rounded to the market tick. |
| `--market` | Market order instead of a limit order. |
| `--order-type` | `GTC` (limit, default) or `FAK`/`FOK` (market). |
| `--max-spend` | Market BUY only: fee-inclusive USD cap (defaults to `--usd`). |
| `--dry-run` | Build + sign locally, print details, do **not** submit. |
| `--yes` | Skip the typed-`YES` confirmation. |

> **Market order semantics** mirror the SDK: a market **BUY** spends a USD `amount`
> (use `--usd`), a market **SELL** delivers `shares` (use `--size`). Mixing them is
> rejected up front.

## Safety

Every real submit shows a preview and requires typing `YES` (unless `--yes`).
Use `--dry-run` to inspect exactly what would be sent. Prices are validated to be
between 0 and 1; sizes must be positive; amounts are rounded to the tick size before
being sent as strings — never floats — to avoid the SDK's float-precision rejections.

## Wallet

The signer key is stored at `~/.config/polymarket/config.json` (chmod 600). The
key in that file is never printed — `poly wallet show` only prints the derived address.

```bash
poly wallet create          # generate a new key
poly wallet import 0x...    # import an existing key
poly wallet show            # show address + config path
poly wallet address         # just the address
poly wallet reset --force   # delete the saved config
```
