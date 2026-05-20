from unittest.mock import MagicMock, patch

import remote
from config import Config


@patch("remote.requests.post")
def test_remote_noop_when_disabled(mock_post):
    config = Config()
    config.remote_logging_enabled = False
    config.remote_base_url = "https://example.com"
    assert remote.post_log(config, "test", "App") is False
    mock_post.assert_not_called()


@patch("remote.requests.post")
def test_remote_posts_when_enabled(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    config = Config()
    config.remote_logging_enabled = True
    config.remote_base_url = "https://example.com"
    assert remote.post_log(config, "test", "App", "1") is True
    mock_post.assert_called_once()
    assert mock_post.call_args[0][0] == "https://example.com/log"
