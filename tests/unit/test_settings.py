"""Configuration tests: safety invariants must hold at load time."""

from __future__ import annotations

import pytest

from harsh_quant_os.config import Settings, SettingsError


@pytest.mark.unit
def test_defaults_are_safe() -> None:
    settings = Settings.load(_env_file=None)

    assert settings.live_trading_enabled is False
    assert settings.paper_trading_enabled is False
    assert settings.broker_provider == ""
    assert settings.cloud_sync_enabled is False
    assert settings.local_agent_enabled is False


@pytest.mark.unit
def test_live_trading_flag_is_rejected() -> None:
    with pytest.raises(SettingsError, match="LIVE_TRADING_ENABLED"):
        Settings.load(_env_file=None, live_trading_enabled=True)


@pytest.mark.security
def test_placeholder_secrets_rejected_outside_development() -> None:
    with pytest.raises(SettingsError, match="Placeholder secrets"):
        Settings.load(_env_file=None, app_env="production")

    with pytest.raises(SettingsError, match="Placeholder secrets"):
        Settings.load(_env_file=None, app_env="staging")


@pytest.mark.unit
def test_placeholder_secrets_allowed_in_development_and_test() -> None:
    assert Settings.load(_env_file=None, app_env="development").missing_secrets()
    assert Settings.load(_env_file=None, app_env="test").missing_secrets()


@pytest.mark.unit
def test_missing_secrets_detection() -> None:
    settings = Settings.load(_env_file=None)

    assert settings.missing_secrets() == [
        "auth_secret_key",
        "database_password",
        "local_agent_token",
    ]


@pytest.mark.unit
def test_real_looking_secret_clears_placeholder_detection() -> None:
    settings = Settings.load(
        _env_file=None,
        app_env="production",
        auth_secret_key="a" * 48,
        database_password="b" * 32,
        local_agent_token="c" * 40,
    )

    assert settings.missing_secrets() == []


@pytest.mark.unit
def test_allowed_origins_are_trimmed() -> None:
    settings = Settings.load(
        _env_file=None,
        api_allowed_origins="http://localhost:3000, https://quant.example.com ,",
    )

    assert settings.allowed_origins == [
        "http://localhost:3000",
        "https://quant.example.com",
    ]


@pytest.mark.unit
def test_invalid_app_env_rejected() -> None:
    with pytest.raises(ValueError):
        Settings.load(_env_file=None, app_env="prod")


@pytest.mark.unit
def test_live_trading_helper_has_no_enabling_code_path() -> None:
    settings = Settings.load(_env_file=None)

    with pytest.raises(SettingsError, match="cannot be enabled by configuration"):
        settings.with_live_trading_approved()
