# poly/groups/data.py
import typer

from .. import context as _context
from ..output import emit
from ..pagination import collect

app = typer.Typer(no_args_is_help=True, help="On-chain portfolio data.")


def _resolve_user(ctx: typer.Context, address: str | None) -> str:
    """Default to your deposit wallet — the SDK-derived account that holds your
    funds — not the signer EOA (which is empty)."""
    if address:
        return address
    return str(_context.secure(ctx).wallet)


@app.command()
def positions(ctx: typer.Context, address: str = typer.Argument(None), limit: int = 20) -> None:
    """List positions for ADDRESS (default: your deposit wallet)."""
    user = _resolve_user(ctx, address)
    emit(ctx.obj.output, collect(_context.public(ctx).list_positions(user=user, page_size=limit)))


@app.command()
def value(ctx: typer.Context, address: str = typer.Argument(None)) -> None:
    """Portfolio value for ADDRESS (default: your deposit wallet)."""
    user = _resolve_user(ctx, address)
    emit(ctx.obj.output, _context.public(ctx).get_portfolio_values(user=user))
