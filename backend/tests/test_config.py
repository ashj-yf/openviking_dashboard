import pytest

from app.core.config import ConfigError, Settings, validate_settings


def _base_settings(**overrides) -> Settings:
    defaults = dict(
        debug=False,
        first_admin_username="admin",
        first_admin_password="admin123",
        jwt_secret="a-very-long-random-secret-value-0123456789",
        secret_key="another-very-long-random-secret-value-9876543210",
        openviking_root_key="root-xyz",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_production_config_passes():
    validate_settings(_base_settings())


def test_missing_first_admin_fails():
    with pytest.raises(ConfigError) as exc:
        validate_settings(_base_settings(first_admin_password=""))
    assert "FIRST_ADMIN" in str(exc.value)


def test_empty_secrets_always_fail():
    with pytest.raises(ConfigError):
        validate_settings(_base_settings(jwt_secret=""))
    with pytest.raises(ConfigError):
        validate_settings(_base_settings(secret_key=""))


def test_example_secrets_rejected_in_production():
    with pytest.raises(ConfigError) as exc:
        validate_settings(_base_settings(jwt_secret="change-me", secret_key="change-me-to-a-long-random-string"))
    assert "JWT_SECRET" in str(exc.value)


def test_missing_root_key_rejected_in_production_but_allowed_in_debug():
    with pytest.raises(ConfigError):
        validate_settings(_base_settings(openviking_root_key=""))
    validate_settings(_base_settings(debug=True, openviking_root_key=""))
