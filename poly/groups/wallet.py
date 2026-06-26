# poly/groups/wallet.py
"""Local wallet/key management backed by config.json."""

import typer
from eth_account import Account

from .. import context as _context
from ..config import CONFIG_PATH, load_config, save_config
from ..context import CliContext
from ..output import emit

app = typer.Typer(no_args_is_help=True, help="Manage the signer key (config.json).")


def _fmt(ctx: typer.Context) -> str:
    return ctx.obj.output if isinstance(ctx.obj, CliContext) else "table"


def _store_key(key: str) -> str:
    key = key if key.startswith("0x") else "0x" + key
    save_config({**load_config(path=CONFIG_PATH), "private_key": key}, path=CONFIG_PATH)
    return Account.from_key(key).address


def _deposit_wallet(ctx: typer.Context) -> str:
    """The SDK-derived deposit wallet that actually holds funds (network call)."""
    try:
        return str(_context.secure(ctx).wallet)
    except Exception as exc:  # never let a network/auth hiccup break `show`
        return f"(unavailable: {type(exc).__name__})"


@app.command()
def create(ctx: typer.Context, force: bool = typer.Option(False, "--force")) -> None:
    """Generate a new random wallet and save it."""
    if load_config(path=CONFIG_PATH).get("private_key") and not force:
        raise SystemExit("A key already exists. Use --force to overwrite.")
    eoa = _store_key(Account.create().key.hex())
    emit(_fmt(ctx), {"signer_eoa": eoa, "config": str(CONFIG_PATH),
                     "note": "run `poly wallet show` to see your deposit wallet"})


@app.command("import")
def import_key(ctx: typer.Context, private_key: str = typer.Argument(...)) -> None:
    """Import an existing private key."""
    eoa = _store_key(private_key)
    emit(_fmt(ctx), {"signer_eoa": eoa, "config": str(CONFIG_PATH),
                     "note": "run `poly wallet show` to see your deposit wallet"})


@app.command()
def show(ctx: typer.Context) -> None:
    """Show your signer EOA and deposit wallet (never prints the key)."""
    cfg = load_config(path=CONFIG_PATH)
    key = cfg.get("private_key")
    eoa = Account.from_key(key).address if key else None
    deposit = _deposit_wallet(ctx) if key else None
    emit(_fmt(ctx), {"signer_eoa": eoa, "deposit_wallet": deposit, "config": str(CONFIG_PATH)})


@app.command()
def address(ctx: typer.Context) -> None:
    """Print your deposit wallet address (the account that holds funds)."""
    emit(_fmt(ctx), {"address": str(_context.secure(ctx).wallet)})


@app.command()
def reset(ctx: typer.Context, force: bool = typer.Option(False, "--force")) -> None:
    """Delete the saved config."""
    if not force:
        raise SystemExit("This deletes your saved key. Re-run with --force to confirm.")
    CONFIG_PATH.unlink(missing_ok=True)
    emit(_fmt(ctx), {"deleted": str(CONFIG_PATH)})
