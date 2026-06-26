# poly/groups/data.py
import typer
from eth_account import Account

from .. import context as _context
from ..output import emit
from ..pagination import collect
from ..config import load_settings

app = typer.Typer(no_args_is_help=True, help="On-chain portfolio data.")


def _resolve_user(ctx, address):
    if address:
        return address
    pk = getattr(ctx.obj, "private_key", None)
    return Account.from_key(load_settings(private_key=pk).private_key).address


@app.command()
def positions(ctx: typer.Context, address: str = typer.Argument(None), limit: int = 20) -> None:
    """List positions for ADDRESS (default: your wallet)."""
    user = _resolve_user(ctx, address)
    emit(ctx.obj.output, collect(_context.public(ctx).list_positions(user=user, page_size=limit)))


@app.command()
def value(ctx: typer.Context, address: str = typer.Argument(None)) -> None:
    """Portfolio value for ADDRESS (default: your wallet)."""
    user = _resolve_user(ctx, address)
    emit(ctx.obj.output, _context.public(ctx).get_portfolio_values(user=user))
