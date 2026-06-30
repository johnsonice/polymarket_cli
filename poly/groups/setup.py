# poly/groups/setup.py
"""First-time setup: store a key in config.json; set up trading approvals."""

import typer
from eth_account import Account

from ..config import CONFIG_PATH, load_config, save_config
from ..context import secure
from ..output import emit


def setup_cmd(ctx: typer.Context, private_key: str = typer.Option(None, "--private-key")) -> None:
    """Configure your signer key (use --private-key, or paste when prompted)."""
    key = private_key or typer.prompt("Signer private key (0x...)", hide_input=True)
    key = key if key.startswith("0x") else "0x" + key
    # Build a new dict — never mutate the existing config in place.
    # Stale keys like "signature_type" are preserved as-is (ignored by the SDK).
    save_config({**load_config(path=CONFIG_PATH), "private_key": key}, path=CONFIG_PATH)
    fmt = getattr(ctx.obj, "output", "table")
    emit(fmt, {"address": Account.from_key(key).address, "config": str(CONFIG_PATH)})


def _is_auto_redeem_skip(result: dict) -> bool:
    # The relayer does not whitelist the auto-redeem operator, but that operator is not
    # needed to TRADE — so a failure to set it is expected and must not fail the command.
    return (not result["ok"]) and ("not in the allowed list" in (result.get("error") or ""))


def approve_cmd(ctx: typer.Context) -> None:
    """Set up one-time trading approvals so the deposit wallet can trade.

    Gasless (paid by the relayer), so it needs the relayer flow
    (POLYMARKET_RELAYER_API_KEY). Approvals are submitted INDIVIDUALLY rather than as
    the all-or-nothing SDK setup_trading_approvals() bundle, so the one operator the
    relayer does not whitelist (the auto-redeem operator, not needed for trading)
    cannot block the rest. Non-interactive — safe to run headless. Idempotent.
    """
    from polymarket._internal.actions.relayer.approvals import _required_trading_approvals

    client = secure(ctx)
    erc20, erc1155 = _required_trading_approvals(client._ctx.environment)
    results: list[dict] = []
    for a in erc20:
        try:
            client.approve_erc20(token_address=a.token_address, spender_address=a.spender,
                                 amount=a.amount).wait()
            results.append({"kind": "erc20", "spender": str(a.spender), "ok": True})
        except Exception as e:  # noqa: BLE001 — report per-approval, never abort the loop
            results.append({"kind": "erc20", "spender": str(a.spender), "ok": False, "error": str(e)[:200]})
    for a in erc1155:
        try:
            client.approve_erc1155_for_all(token_address=a.token_address,
                                           operator_address=a.operator, approved=True).wait()
            results.append({"kind": "erc1155", "operator": str(a.operator), "ok": True})
        except Exception as e:  # noqa: BLE001
            results.append({"kind": "erc1155", "operator": str(a.operator), "ok": False, "error": str(e)[:200]})

    trading_ok = all(r["ok"] for r in results if not _is_auto_redeem_skip(r))
    fmt = getattr(ctx.obj, "output", "table")
    emit(fmt, {"trading_approved": trading_ok, "results": results})
    if not trading_ok:
        raise typer.Exit(1)
