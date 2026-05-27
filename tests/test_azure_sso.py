import sqlalchemy as sa

from memlord.config import Settings
from memlord.models.user import User


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
