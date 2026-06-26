from typer.testing import CliRunner
from poly.cli import app

runner = CliRunner()

def test_help_lists_groups():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "buy" in result.output
