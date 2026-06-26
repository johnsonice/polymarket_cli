"""Environment loading and polymarket-client client construction.

The CLI authenticates with a single signer private key. By default the SDK
derives the deterministic Deposit Wallet (signature type 3 / POLY_1271) from that
key and trades from it — the flow the legacy ``py-clob-client-v2`` could not do.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Immutable view of everything needed to build a trading client.

    Secret fields are excluded from ``repr`` so a stray ``print(settings)`` or a
    traceback that captures frame locals never leaks the private key or API key.
    """

    private_key: str = field(repr=False)
    wallet_address: str | None = None
    relayer_api_key: str | None = field(default=None, repr=False)
    relayer_api_key_address: str | None = None


def _normalize_private_key(key: str) -> str:
    """Ensure the private key carries the ``0x`` prefix the SDK expects."""
    key = key.strip()
    return key if key.startswith("0x") else "0x" + key


def load_settings(env: dict | None = None) -> Settings:
    """Read and validate required environment variables.

    ``env`` defaults to ``os.environ`` (after loading ``.env``); it is injectable
    so tests need not mutate the real process environment. Raises ``SystemExit``
    with a friendly message when the required key is missing.
    """
    if env is None:
        load_dotenv()
        env = os.environ

    private_key = (env.get("POLYMARKET_PRIVATE_KEY") or "").strip()
    if not private_key:
        raise SystemExit(
            "Missing required env var POLYMARKET_PRIVATE_KEY. "
            "Copy .env.example to .env and fill it in."
        )

    return Settings(
        private_key=_normalize_private_key(private_key),
        wallet_address=(env.get("POLYMARKET_WALLET_ADDRESS") or "").strip() or None,
        relayer_api_key=(env.get("POLYMARKET_RELAYER_API_KEY") or "").strip() or None,
        relayer_api_key_address=(
            (env.get("POLYMARKET_RELAYER_API_KEY_ADDRESS") or "").strip() or None
        ),
    )


def build_public_client():
    """Construct an unauthenticated client for public market reads."""
    from polymarket import PublicClient

    return PublicClient()


def build_secure_client(settings: Settings | None = None):
    """Construct an authenticated trading client from settings.

    Imports the SDK lazily so that pure-logic imports (and tests of
    ``load_settings``) do not pay the cost of importing the whole SDK.
    """
    from polymarket import RelayerApiKey, SecureClient

    settings = settings or load_settings()

    api_key = None
    if settings.relayer_api_key and settings.relayer_api_key_address:
        api_key = RelayerApiKey(
            key=settings.relayer_api_key,
            address=settings.relayer_api_key_address,
        )

    return SecureClient.create(
        private_key=settings.private_key,
        wallet=settings.wallet_address,
        api_key=api_key,
    )
