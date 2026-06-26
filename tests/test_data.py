from types import SimpleNamespace
from typer.testing import CliRunner
from poly.cli import app
from poly import context

runner = CliRunner()


class FakePub:
    def list_positions(self, user=None, page_size=20):
        return SimpleNamespace(first_page=lambda: SimpleNamespace(items=[{"outcome": "Yes", "size": "5"}], has_next=False))


def test_positions_json(monkeypatch):
    monkeypatch.setattr(context, "public", lambda ctx: FakePub())
    result = runner.invoke(app, ["-o", "json", "data", "positions", "0xWALLET"])
    assert result.exit_code == 0 and "Yes" in result.output
