import pytest
from pydantic import ValidationError


def test_root_path_default_empty():
    from memlord.config import Settings
    s = Settings(base_url="http://localhost:8000", oauth_jwt_secret="x")
    assert s.root_path == ""


def test_root_path_custom():
    from memlord.config import Settings
    s = Settings(base_url="http://localhost:8000", oauth_jwt_secret="x", root_path="/memlord")
    assert s.root_path == "/memlord"


def test_root_path_validation_passes():
    from memlord.config import Settings
    s = Settings(
        base_url="https://example.com/memlord",
        oauth_jwt_secret="x",
        root_path="/memlord",
    )
    assert s.root_path == "/memlord"


def test_root_path_validation_fails():
    from memlord.config import Settings
    with pytest.raises(ValidationError):
        Settings(
            base_url="https://example.com/wrong",
            oauth_jwt_secret="x",
            root_path="/memlord",
        )


def test_root_path_empty_no_validation():
    from memlord.config import Settings
    # root_path="" should not trigger validation regardless of base_url
    s = Settings(base_url="https://example.com", oauth_jwt_secret="x", root_path="")
    assert s.root_path == ""
