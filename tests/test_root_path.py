from unittest.mock import patch

import pytest
from pydantic import ValidationError
from starlette.responses import Response


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


def test_set_session_cookie_path():
    """Cookie should use root_path as its path."""
    with patch("memlord.ui.utils.settings") as mock, \
         patch("memlord.ui.utils.make_session_token", return_value="fake_token"):
        mock.root_path = "/memlord"
        mock.base_url = "http://localhost:8000"

        from memlord.ui.utils import delete_session_cookie, set_session_cookie

        resp = Response()
        set_session_cookie(resp, 1)
        cookie_header = resp.headers.get("set-cookie", "")
        assert "; Path=/memlord/" in cookie_header

        resp2 = Response()
        delete_session_cookie(resp2)
        cookie_header2 = resp2.headers.get("set-cookie", "")
        assert "; Path=/memlord/" in cookie_header2


def test_set_session_cookie_path_default():
    """Cookie should use '/' path when root_path is empty."""
    with patch("memlord.ui.utils.settings") as mock, \
         patch("memlord.ui.utils.make_session_token", return_value="fake_token"):
        mock.root_path = ""
        mock.base_url = "http://localhost:8000"

        from memlord.ui.utils import set_session_cookie

        resp = Response()
        set_session_cookie(resp, 1)
        cookie_header = resp.headers.get("set-cookie", "")
        assert "; Path=/" in cookie_header


def test_root_path_in_jinja_globals():
    """Templates should have root_path available as a Jinja global."""
    from memlord.main import app
    from memlord.ui.utils import templates
    assert "root_path" in templates.env.globals
