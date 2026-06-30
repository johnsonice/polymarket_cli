"""Config-file wallet model and client construction.

Key resolution order: --private-key flag > POLYMARKET_PRIVATE_KEY env >
~/.config/polymarket/config.json. The project .env is intentionally NOT read.

Note: --signature-type was intentionally removed. The SDK derives the deposit
wallet (type-3 / POLY_1271) deterministically from the private key; no other
signature type is supported via SecureClient.create().
"""

import dataclasses
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
CONFIG_PATH = _CONFIG_HOME / "polymarket" / "config.json"


@dataclass(frozen=True)
class Settings:
    private_key: str = field(repr=False)
    wallet_address: str | None = None


def load_config(path: Path | None = None) -> dict:
    """Load config JSON from *path* (default: module-level CONFIG_PATH).

    Using None as the default lets callers and tests patch the module-level
    CONFIG_PATH and have the change take effect without passing path= explicitly.
    """
    p = path if path is not None else CONFIG_PATH
    try:
        return json.loads(Path(p).read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Config file {p} is not valid JSON: {exc}")


def save_config(data: dict, path: Path | None = None) -> None:
    p = Path(path) if path is not None else Path(CONFIG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))
    p.chmod(0o600)


def resolve_private_key(flag: str | None = None, env: str | None = None, config: str | None = None) -> str | None:
    return flag or env or config or None


def _normalize_key(key: str) -> str:
    key = key.strip()
    return key if key.startswith("0x") else "0x" + key


def load_settings(*, private_key: str | None = None, path: Path | None = None) -> Settings:
    """Load and validate settings.

    *path* defaults to the module-level CONFIG_PATH so that tests can patch it
    via ``monkeypatch.setattr(config, "CONFIG_PATH", ...)``.
    """
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
    # Ignore any stale "signature_type" key — the SDK supports only the
    # deposit-wallet derivation and has no signature_type parameter.
    return Settings(private_key=_normalize_key(key), wallet_address=cfg.get("wallet_address"))


# Base-URL overrides. If a POLYMARKET_*_URL env var is set, that host is pointed
# at a custom endpoint (e.g. a regional 1:1 reverse proxy used to reach Polymarket
# from an allowed region) while EVERYTHING ELSE in the environment — chain id and
# all contract addresses — stays production. This is safe because orders are
# EIP-712 signed over the production contracts; only the transport URL changes.
# Unset => the official Polymarket endpoints (default behavior, unchanged).
_URL_ENV = {
    "clob_url": "POLYMARKET_CLOB_URL",
    "gamma_url": "POLYMARKET_GAMMA_URL",
    "data_url": "POLYMARKET_DATA_URL",
    "relayer_url": "POLYMARKET_RELAYER_URL",
    "rfq_url": "POLYMARKET_RFQ_URL",
    "rpc_url": "POLYMARKET_RPC_URL",
}


def resolve_environment():
    """Return the SDK Environment, with any per-host URL overrides from the
    POLYMARKET_*_URL env vars applied on top of PRODUCTION. No env vars set
    (the common case) returns PRODUCTION unchanged."""
    from polymarket.environments import PRODUCTION

    overrides = {field: os.environ[env] for field, env in _URL_ENV.items() if os.environ.get(env)}
    return dataclasses.replace(PRODUCTION, **overrides) if overrides else PRODUCTION


def resolve_relayer_api_key(private_key: str):
    """Build the SDK RelayerApiKey from env, or None.

    Polymarket's deposit-wallet (gasless) flow — required to SUBMIT live orders and to
    run gasless trading approvals — needs a Relayer/Builder API key. That key is a UUID
    minted at polymarket.com (Settings -> API Keys) and registered to your signer EOA;
    it is NOT derivable from the private key, so it must be supplied explicitly via
    POLYMARKET_RELAYER_API_KEY. POLYMARKET_RELAYER_ADDRESS overrides the on-key address
    (defaults to the signer's EOA, which is what the key is registered to).

    Unset (the default) returns None => the EOA flow: public reads and LOCAL signing
    work, but live order submission is rejected by CLOB ("maker address not allowed,
    use the deposit wallet flow")."""
    key = os.environ.get("POLYMARKET_RELAYER_API_KEY")
    if not key:
        return None
    from polymarket import RelayerApiKey

    address = os.environ.get("POLYMARKET_RELAYER_ADDRESS")
    if not address:
        from eth_account import Account

        address = Account.from_key(private_key).address
    return RelayerApiKey(key=key, address=address)


def build_public_client():
    from polymarket import PublicClient
    return PublicClient(resolve_environment())


def build_secure_client(settings: Settings):
    from polymarket import SecureClient
    return SecureClient.create(
        private_key=settings.private_key,
        wallet=settings.wallet_address,
        environment=resolve_environment(),
        api_key=resolve_relayer_api_key(settings.private_key),
    )
