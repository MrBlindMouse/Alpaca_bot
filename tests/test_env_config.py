import os
import tempfile

import pytest

from env_config import MARGIN_MAX, MARGIN_MIN, read_margin, validate_margin, write_margin


def test_validate_margin_range():
    validate_margin(0.05)
    with pytest.raises(ValueError):
        validate_margin(0.01)
    with pytest.raises(ValueError):
        validate_margin(0.20)


def test_write_margin_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, ".env")
        with open(path, "w", encoding="utf-8") as f:
            f.write("VERSION=PAPER\nMARGIN=0.05\nOTHER=1\n")
        write_margin(0.10, path=path)
        assert read_margin(path=path) == 0.10
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "OTHER=1" in content
        assert "MARGIN=0.1" in content or "MARGIN=0.10" in content
