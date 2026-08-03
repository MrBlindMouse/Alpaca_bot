import os
from unittest.mock import patch

import pytest

from config import Config, _parse_bool


def test_parse_bool_defaults():
    assert _parse_bool(None) is False
    assert _parse_bool("") is False
    assert _parse_bool("true") is True
    assert _parse_bool("FALSE") is False


@patch("config.dotenv_values")
def test_config_remote_disabled_by_default(mock_env):
    mock_env.return_value = {
        "VERSION": "PAPER",
        "PAPER_KEY": "k",
        "PAPER_SECRET": "s",
        "MARGIN": "0.05",
    }
    config = Config()
    config.update()
    assert config.remote_logging_enabled is False
    assert config.remote_base_url == ""
    assert config.remote_webhook_secret == ""
    assert config.paper is True


@patch("config.dotenv_values")
def test_config_remote_enabled(mock_env):
    mock_env.return_value = {
        "VERSION": "PAPER",
        "PAPER_KEY": "k",
        "PAPER_SECRET": "s",
        "MARGIN": "0.05",
        "REMOTE_LOGGING_ENABLED": "true",
        "REMOTE_BASE_URL": "https://example.com/hook/",
        "REMOTE_WEBHOOK_SECRET": "sekrit",
    }
    config = Config()
    config.update()
    assert config.remote_logging_enabled is True
    assert config.remote_base_url == "https://example.com/hook"
    assert config.remote_webhook_secret == "sekrit"


@patch("config.dotenv_values")
def test_config_missing_margin(mock_env):
    mock_env.return_value = {
        "VERSION": "PAPER",
        "PAPER_KEY": "k",
        "PAPER_SECRET": "s",
    }
    with pytest.raises(ValueError, match="MARGIN"):
        Config().update()
