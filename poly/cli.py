# poly/cli.py
import typer

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Polymarket CLI.")


@app.command()
def buy() -> None:
    """Buy an outcome (implemented in Task 10)."""
    raise typer.Exit(0)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    main()
