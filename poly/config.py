"""Config-file wallet model and client construction.

Key resolution order: --private-key flag > POLYMARKET_PRIVATE_KEY env >
~/.config/polymarket/config.json. The project .env is intentionally NOT read.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
CONFIG_PATH = _CONFIG_HOME / "polymarket" / "config.json"
DEFAULT_SIGNATURE_TYPE = 3


@dataclass(frozen=True)
class Settings:
    private_key: str = field(repr=False)
    signature_type: int = DEFAULT_SIGNATURE_TYPE
    wallet_address: str | None = None


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Config file {path} is not valid JSON: {exc}")


def save_config(data: dict, path: Path = CONFIG_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def resolve_private_key(flag=None, env=None, config=None) -> str | None:
    return flag or env or config or None


def _normalize_key(key: str) -> str:
    key = key.strip()
    return key if key.startswith("0x") else "0x" + key


def load_settings(*, private_key=None, signature_type=None, path: Path = CONFIG_PATH) -> Settings:
    cfg = load_config(path)
    key = resolve_private_key(
        flag=private_key,
        env=(os.environ.get("POLYMARKET_PRIVATE_KEY") or "").strip() or None,
        config=cfg.get("private_key"),
    )
    if not key:
        raise SystemExit(
            "No private key configured. Run `poly setup` or `poly wallet import 0x...`, "
            "or pass --private-key / set POLYMARKET_PRIVATE_KEY."
        )
    sig = signature_type if signature_type is not None else int(cfg.get("signature_type", DEFAULT_SIGNATURE_TYPE))
    return Settings(private_key=_normalize_key(key), signature_type=sig, wallet_address=cfg.get("wallet_address"))


def build_public_client():
    from polymarket import PublicClient
    return PublicClient()


def build_secure_client(settings: Settings):
    from polymarket import SecureClient
    return SecureClient.create(private_key=settings.private_key, wallet=settings.wallet_address)
