# poly/cli.py
import typer

from .context import CliContext
from .groups import wallet
from .groups import setup as setup_group

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Polymarket CLI.")
_OUTPUT = {"fmt": "table"}  # mirrored for main()'s error envelope

app.add_typer(wallet.app, name="wallet")
app.command("setup")(setup_group.setup_cmd)


@app.callback()
def root(
    ctx: typer.Context,
    output: str = typer.Option("table", "--output", "-o", help="table or json"),
    private_key: str = typer.Option(None, "--private-key", help="Override signer key."),
    signature_type: int = typer.Option(None, "--signature-type", help="0/1/2/3 (default 3)."),
) -> None:
    if output not in ("table", "json"):
        raise typer.BadParameter("--output must be 'table' or 'json'")
    _OUTPUT["fmt"] = output
    ctx.obj = CliContext(output=output, private_key=private_key, signature_type=signature_type)


@app.command()
def buy() -> None:
    """Buy an outcome (implemented in Task 10)."""
    raise typer.Exit(0)


def main() -> int:
    import click
    from polymarket import PolymarketError
    from .output import print_error
    try:
        app(standalone_mode=False)
        return 0
    except (click.exceptions.Abort, KeyboardInterrupt):
        print_error(_OUTPUT["fmt"], "aborted")
        return 1
    except click.exceptions.ClickException as exc:  # usage errors
        exc.show()
        return exc.exit_code
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print_error(_OUTPUT["fmt"], exc.code)
            return 1
        return exc.code or 0
    except (ValueError, PolymarketError) as exc:
        print_error(_OUTPUT["fmt"], str(exc))
        return 1


if __name__ == "__main__":
    main()
