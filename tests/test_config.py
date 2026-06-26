"""Unit tests for environment loading."""

import pytest

from poly.config import Settings, load_settings


def test_load_settings_requires_private_key():
    with pytest.raises(SystemExit):
        load_settings(env={})


def test_load_settings_normalizes_0x_prefix():
    settings = load_settings(env={"POLYMARKET_PRIVATE_KEY": "abc123"})
    assert settings.private_key == "0xabc123"


def test_load_settings_keeps_existing_0x_prefix():
    settings = load_settings(env={"POLYMARKET_PRIVATE_KEY": "0xabc123"})
    assert settings.private_key == "0xabc123"


def test_load_settings_reads_optional_fields():
    settings = load_settings(
        env={
            "POLYMARKET_PRIVATE_KEY": "0xkey",
            "POLYMARKET_WALLET_ADDRESS": "0xwallet",
            "POLYMARKET_RELAYER_API_KEY": "rk",
            "POLYMARKET_RELAYER_API_KEY_ADDRESS": "0xrelayer",
        }
    )
    assert settings.wallet_address == "0xwallet"
    assert settings.relayer_api_key == "rk"
    assert settings.relayer_api_key_address == "0xrelayer"


def test_load_settings_blank_optionals_become_none():
    settings = load_settings(
        env={"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_WALLET_ADDRESS": "   "}
    )
    assert settings.wallet_address is None


def test_settings_is_frozen():
    settings = load_settings(env={"POLYMARKET_PRIVATE_KEY": "0xkey"})
    with pytest.raises(Exception):
        settings.private_key = "mutated"  # type: ignore[misc]
    assert isinstance(settings, Settings)
