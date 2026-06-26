# poly/groups/setup.py
"""First-time setup: store a key in config.json (migrates an old .env key)."""

import typer
from eth_account import Account

from ..config import CONFIG_PATH, DEFAULT_SIGNATURE_TYPE, load_config, save_config
from ..output import emit


def setup_cmd(ctx: typer.Context, private_key: str = typer.Option(None, "--private-key")) -> None:
    """Configure your signer key (use --private-key, or paste when prompted)."""
    key = private_key or typer.prompt("Signer private key (0x...)", hide_input=True)
    key = key if key.startswith("0x") else "0x" + key
    cfg = load_config(path=CONFIG_PATH)
    cfg["private_key"] = key
    cfg.setdefault("signature_type", DEFAULT_SIGNATURE_TYPE)
    save_config(cfg, path=CONFIG_PATH)
    fmt = getattr(ctx.obj, "output", "table")
    emit(fmt, {"address": Account.from_key(key).address, "config": str(CONFIG_PATH)})
