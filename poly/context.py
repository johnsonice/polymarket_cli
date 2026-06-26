# poly/context.py
import typer
from dataclasses import dataclass, field

from . import config


@dataclass
class CliContext:
    output: str = "table"
    private_key: str | None = field(default=None, repr=False)
    signature_type: int | None = None
    _public: object = None
    _secure: object = None


def _ctx(ctx: typer.Context) -> CliContext:
    if not isinstance(ctx.obj, CliContext):
        ctx.obj = CliContext()
    return ctx.obj


def public(ctx: typer.Context):
    c = _ctx(ctx)
    if c._public is None:
        c._public = config.build_public_client()
    return c._public


def secure(ctx: typer.Context):
    c = _ctx(ctx)
    if c._secure is None:
        settings = config.load_settings(private_key=c.private_key, signature_type=c.signature_type)
        c._secure = config.build_secure_client(settings)
    return c._secure
