"""Output formatting: one place for json vs table rendering and errors."""

import json
import sys
from decimal import Decimal
from typing import Any


def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump(mode="json"))
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def _render_table(data: Any) -> str:
    data = to_jsonable(data)
    if isinstance(data, list):
        if not data:
            return "(no results)"
        cols = list({k: None for row in data for k in (row if isinstance(row, dict) else {})})
        widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in data)) for c in cols}
        header = "  ".join(c.ljust(widths[c]) for c in cols)
        rows = ["  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols) for r in data]
        return "\n".join([header, *rows])
    if isinstance(data, dict):
        w = max((len(k) for k in data), default=0)
        return "\n".join(f"{k.ljust(w)}  {v}" for k, v in data.items())
    return str(data)


def emit(fmt: str, data: Any) -> None:
    if fmt == "json":
        print(json.dumps(to_jsonable(data), indent=2))
    else:
        print(_render_table(data))


def print_error(fmt: str, message: str) -> None:
    if fmt == "json":
        print(json.dumps({"error": message}))
    else:
        print(f"Error: {message}", file=sys.stderr)
