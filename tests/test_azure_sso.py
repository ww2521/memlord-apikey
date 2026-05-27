from fastapi import Response

from memlord.config import Settings
from memlord.dao.user import UserDao
from memlord.models.user import User
from memlord.ui.utils import set_session_cookie


def test_set_session_cookie_sets_cookie():
    """set_session_cookie should set memlord_session cookie."""
    response = Response()
    set_session_cookie(response, 42)
    cookie = response.headers.get("set-cookie", "")
    assert "memlord_session" in cookie
    assert "HttpOnly" in cookie


def test_azure_sso_defaults():
    s = Settings(_env_file=None)
    assert s.azure_sso_enabled is False
    assert s.azure_client_id is None
    assert s.azure_client_secret is None
    assert s.azure_tenant_id is None
    assert s.azure_redirect_uri is None
    assert s.azure_scope == "openid profile email"
    assert s.azure_login_button_text == "Sign in with Azure AD"
    assert s.azure_allowed_email_domains is None
    assert s.azure_auto_register is True
    assert s.local_password_login_enabled is True
    assert s.local_registration_enabled is True


def test_azure_sso_from_env(monkeypatch):
    monkeypatch.setenv("MEMLORD_AZURE_SSO_ENABLED", "true")
    monkeypatch.setenv("MEMLORD_AZURE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("MEMLORD_AZURE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("MEMLORD_AZURE_TENANT_ID", "test-tenant")
    monkeypatch.setenv("MEMLORD_AZURE_REDIRECT_URI", "https://example.com/auth/azure/callback")
    monkeypatch.setenv("MEMLORD_AZURE_SCOPE", "openid email")
    monkeypatch.setenv("MEMLORD_AZURE_LOGIN_BUTTON_TEXT", "Login with Company SSO")
    monkeypatch.setenv("MEMLORD_AZURE_ALLOWED_EMAIL_DOMAINS", "company.com,sub.com")
    monkeypatch.setenv("MEMLORD_AZURE_AUTO_REGISTER", "false")
    monkeypatch.setenv("MEMLORD_LOCAL_PASSWORD_LOGIN_ENABLED", "false")
    monkeypatch.setenv("MEMLORD_LOCAL_REGISTRATION_ENABLED", "false")
    s = Settings(_env_file=None)
    assert s.azure_sso_enabled is True
    assert s.azure_client_id == "test-client-id"
    assert s.azure_client_secret == "test-secret"
    assert s.azure_tenant_id == "test-tenant"
    assert s.azure_redirect_uri == "https://example.com/auth/azure/callback"
    assert s.azure_scope == "openid email"
    assert s.azure_login_button_text == "Login with Company SSO"
    assert s.azure_allowed_email_domains == ["company.com", "sub.com"]
    assert s.azure_auto_register is False
    assert s.local_password_login_enabled is False
    assert s.local_registration_enabled is False


def test_user_model_has_azure_columns():
    assert hasattr(User, "azure_sub")
    assert hasattr(User, "auth_method")


def test_user_model_hashed_password_nullable():
    assert User.hashed_password.property.columns[0].nullable is True


async def test_get_or_create_by_email_for_sso_existing_user(session):
    """Existing user should be returned and azure_sub updated."""
    user = await UserDao(session).create(
        email="existing@test.com",
        display_name="Existing User",
        hashed_password="hashed",
    )
    result = await UserDao(session).get_or_create_by_email_for_sso(
        email="existing@test.com",
        display_name="Existing User",
        azure_sub="azure-sub-123",
    )
    assert result.id == user.id
    assert result.email == "existing@test.com"
    assert result.display_name == "Existing User"


async def test_get_or_create_by_email_for_sso_new_user(session):
    """New user should be auto-created with azure fields set."""
    result = await UserDao(session).get_or_create_by_email_for_sso(
        email="new@test.com",
        display_name="New SSO User",
        azure_sub="azure-sub-456",
    )
    assert result.id is not None
    assert result.email == "new@test.com"
    assert result.display_name == "New SSO User"


async def test_get_or_create_by_email_for_sso_auto_register_false(session):
    """When auto_register=False and user doesn't exist, return None."""
    result = await UserDao(session).get_or_create_by_email_for_sso(
        email="unknown@test.com",
        display_name="Unknown",
        azure_sub="azure-sub-789",
        auto_register=False,
    )
    assert result is None


def test_session_middleware_installed():
    """SessionMiddleware must be present for authlib OAuth state management."""
    from starlette.middleware.sessions import SessionMiddleware

    from memlord.main import app

    middlewares = [m.cls for m in app.user_middleware]
    assert SessionMiddleware in middlewares


def test_create_azure_router_returns_none_when_not_configured():
    """When azure SSO is not configured, create_azure_router returns None."""
    from memlord.sso import create_azure_router
    result = create_azure_router()
    assert result is None


def test_email_domain_allowed():
    """Test the _is_email_allowed helper."""
    from memlord.sso import _is_email_allowed
    # No whitelist = allow all
    assert _is_email_allowed("user@any.com", None) is True
    # Matching domain
    assert _is_email_allowed("user@company.com", ["company.com"]) is True
    # Non-matching domain
    assert _is_email_allowed("user@other.com", ["company.com"]) is False
    # Multiple domains
    assert _is_email_allowed("user@sub.com", ["company.com", "sub.com"]) is True


async def test_login_page_shows_azure_button_when_enabled(monkeypatch):
    """When Azure SSO is enabled, login page should contain Azure button."""
    monkeypatch.setattr("memlord.ui.login.settings", type("obj", (), {
        "azure_sso_enabled": True,
        "azure_login_button_text": "Sign in with Azure AD",
        "local_password_login_enabled": True,
        "local_registration_enabled": True,
    })())
    from memlord.main import app
    from starlette.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/ui/login")
    assert resp.status_code == 200
    assert "Sign in with Azure AD" in resp.text
    assert "/auth/azure/login" in resp.text


async def test_login_page_hides_password_form_when_disabled(monkeypatch):
    """When local_password_login_enabled=False, password form should not appear."""
    monkeypatch.setattr("memlord.ui.login.settings", type("obj", (), {
        "azure_sso_enabled": True,
        "azure_login_button_text": "SSO",
        "local_password_login_enabled": False,
        "local_registration_enabled": True,
    })())
    from memlord.main import app
    from starlette.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/ui/login")
    assert resp.status_code == 200
    assert "SSO" in resp.text
    assert '<input type="password"' not in resp.text


async def test_register_page_redirects_when_disabled(monkeypatch):
    """When local_registration_enabled=False, GET /ui/register should redirect to login."""
    monkeypatch.setattr("memlord.ui.login.settings", type("obj", (), {
        "azure_sso_enabled": False,
        "azure_login_button_text": "SSO",
        "local_password_login_enabled": True,
        "local_registration_enabled": False,
    })())
    from memlord.main import app
    from starlette.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/ui/register", follow_redirects=False)
    assert resp.status_code == 303
    assert "/ui/login" in resp.headers["location"]


async def test_login_page_hides_register_link_when_disabled(monkeypatch):
    """When local_registration_enabled=False, register link should not appear."""
    monkeypatch.setattr("memlord.ui.login.settings", type("obj", (), {
        "azure_sso_enabled": False,
        "azure_login_button_text": "SSO",
        "local_password_login_enabled": True,
        "local_registration_enabled": False,
    })())
    from memlord.main import app
    from starlette.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/ui/login")
    assert resp.status_code == 200
    assert "Create one" not in resp.text
