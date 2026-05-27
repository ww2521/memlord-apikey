# Azure AD SSO Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Azure AD (Entra ID) SSO login to Memlord's Web UI, with configurable auto-registration, login button text, and local auth toggles.

**Architecture:** A new `src/memlord/sso.py` module provides two routes (`/auth/azure/login` and `/auth/azure/callback`) using authlib's Starlette OAuth integration. authlib's `authorize_redirect` stores OAuth state in `request.session`, which requires Starlette's `SessionMiddleware`. The callback finds or creates a Memlord user and reuses the existing `make_session_token()` session mechanism. Login page template is updated to show an Azure button and conditionally hide password/registration UI.

**Tech Stack:** Python 3.12, FastAPI, authlib (>=1.3 Starlette integration), SQLAlchemy Core, Alembic, Jinja2

---

### Task 1: Add configuration fields to Settings

**Files:**
- Modify: `src/memlord/config.py:31-32` (add fields between `smtp_tls` and `LOG_LEVEL`)
- Test: `tests/test_azure_sso.py`

**Step 1: Write the failing test**

Create `tests/test_azure_sso.py`:

```python
from memlord.config import Settings


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_azure_sso.py -v`
Expected: FAIL — `AttributeError: type object 'Settings' has no attribute 'azure_sso_enabled'`

**Step 3: Write minimal implementation**

In `src/memlord/config.py`, add these fields to the `Settings` class (between `smtp_tls` and `LOG_LEVEL`):

```python
    azure_sso_enabled: bool = False
    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    azure_tenant_id: str | None = None
    azure_redirect_uri: str | None = None
    azure_scope: str = "openid profile email"
    azure_login_button_text: str = "Sign in with Azure AD"
    azure_allowed_email_domains: list[str] | None = None
    azure_auto_register: bool = True

    local_password_login_enabled: bool = True
    local_registration_enabled: bool = True
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_azure_sso.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/memlord/config.py tests/test_azure_sso.py
git commit -m "feat: add Azure SSO and local auth toggle config fields"
```

---

### Task 2: Update User model with Azure SSO columns

**Files:**
- Modify: `src/memlord/models/user.py:6-16`
- Test: `tests/test_azure_sso.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_azure_sso.py`:

```python
from memlord.models.user import User


def test_user_model_has_azure_columns():
    assert hasattr(User, "azure_sub")
    assert hasattr(User, "auth_method")


def test_user_model_hashed_password_nullable():
    assert User.hashed_password.property.columns[0].nullable is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_azure_sso.py::test_user_model_has_azure_columns -v`
Expected: FAIL — `AssertionError`

**Step 3: Write minimal implementation**

In `src/memlord/models/user.py`, add two new columns and change `hashed_password` to nullable:

```python
class User(Base):
    __tablename__ = "users"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    email = sa.Column(sa.Text, unique=True, nullable=False)
    display_name = sa.Column(sa.Text, nullable=False, server_default="")
    hashed_password = sa.Column(sa.Text, nullable=True)
    email_verified = sa.Column(sa.Boolean, nullable=False, server_default=sa.false())
    azure_sub = sa.Column(sa.String(255), unique=True, nullable=True)
    auth_method = sa.Column(sa.String(32), nullable=False, server_default="local")
    created_at = sa.Column(
        sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_azure_sso.py::test_user_model_has_azure_columns tests/test_azure_sso.py::test_user_model_hashed_password_nullable -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/memlord/models/user.py tests/test_azure_sso.py
git commit -m "feat: add azure_sub and auth_method columns to User model"
```

---

### Task 3: Create Alembic migration

**Files:**
- Create: `migrations/versions/2026_05_27_0001-<hash>_azure_sso_user_fields.py`

**Step 1: Run alembic revision —autogenerate**

Run: `MEMLORD_DB_URL=postgresql+asyncpg://postgres:postgres@localhost/memlord alembic revision --autogenerate -m "azure sso user fields"`

If autogenerate is not available (no running DB), create the migration manually. The file should look like:

```python
"""azure sso user fields

Revision ID: <auto>
Revises: 7e2e8e52e1c5439a
Create Date: 2026-05-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<auto>"
down_revision: Union[str, Sequence[str], None] = "7e2e8e52e1c5439a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("azure_sub", sa.String(255), unique=True, nullable=True))
    op.add_column("users", sa.Column("auth_method", sa.String(32), server_default="local", nullable=False))
    op.alter_column("users", "hashed_password", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "hashed_password", existing_type=sa.Text(), nullable=False)
    op.drop_column("users", "auth_method")
    op.drop_column("users", "azure_sub")
```

**Step 2: Verify migration**

Run: `MEMLORD_DB_URL=postgresql+asyncpg://postgres:postgres@localhost/memlord alembic upgrade head`
Expected: No errors

**Step 3: Commit**

```bash
git add migrations/versions/
git commit -m "feat: add migration for azure_sso user fields"
```

---

### Task 4: Add UserDao.get_or_create_by_email_for_sso() method

**Files:**
- Modify: `src/memlord/dao/user.py:78-95` (add method after `create()`)
- Test: `tests/test_azure_sso.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_azure_sso.py`:

```python
import pytest
from memlord.dao.user import UserDao


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_azure_sso.py -k "sso" -v`
Expected: FAIL — `AttributeError: 'UserDao' object has no attribute 'get_or_create_by_email_for_sso'`

**Step 3: Write minimal implementation**

In `src/memlord/dao/user.py`, add this method after `create()`:

```python
    async def get_or_create_by_email_for_sso(
        self,
        email: str,
        display_name: str,
        azure_sub: str,
        auto_register: bool = True,
    ) -> UserInfo | None:
        email = email.strip().lower()
        row = (
            (
                await self._s.execute(
                    select(
                        User.id,
                        User.display_name,
                        User.email,
                        User.email_verified,
                        User.azure_sub,
                    ).where(User.email == email)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is not None:
            if row["azure_sub"] is None:
                await self._s.execute(
                    update(User).where(User.id == row["id"]).values(azure_sub=azure_sub)
                )
            return UserInfo(
                id=row["id"],
                display_name=row["display_name"],
                email=row["email"],
                email_verified=row["email_verified"],
            )
        if not auto_register:
            return None
        user_id = await self._s.scalar(
            insert(User).values(
                email=email,
                display_name=display_name.strip(),
                hashed_password=None,
                azure_sub=azure_sub,
                auth_method="azure_sso",
            ).returning(User.id)
        )
        assert user_id is not None
        await WorkspaceDao(self._s, user_id).create_personal()
        return UserInfo(
            id=user_id,
            display_name=display_name.strip(),
            email=email,
            email_verified=False,
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_azure_sso.py -k "sso" -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add src/memlord/dao/user.py tests/test_azure_sso.py
git commit -m "feat: add UserDao.get_or_create_by_email_for_sso method"
```

---

### Task 5: Extract `_set_session` to shared utility

The existing `_set_session()` in `ui/login.py:22-29` is needed by both `login.py` and the new `sso.py`. Extract it to `ui/utils.py` to avoid duplication.

**Files:**
- Modify: `src/memlord/ui/utils.py` (add `set_session_cookie` function)
- Modify: `src/memlord/ui/login.py` (import from utils, remove local `_set_session`)
- Test: `tests/test_azure_sso.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_azure_sso.py`:

```python
from fastapi import Response
from memlord.ui.utils import set_session_cookie


def test_set_session_cookie_sets_cookie():
    """set_session_cookie should set memlord_session cookie."""
    response = Response()
    set_session_cookie(response, 42)
    assert "memlord_session" in response.headers.get("set-cookie", "")
    assert "httponly" in response.headers.get("set-cookie", "")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_azure_sso.py::test_set_session_cookie_sets_cookie -v`
Expected: FAIL — `ImportError: cannot import name 'set_session_cookie' from 'memlord.ui.utils'`

**Step 3: Write the implementation**

**3a.** In `src/memlord/ui/utils.py`, add the function and update `__all__`:

```python
from fastapi import Response


def set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        "memlord_session",
        make_session_token(user_id),
        httponly=True,
        samesite="lax",
        secure=settings.base_url.startswith("https"),
    )
```

Update `__all__` at the bottom:

```python
__all__ = ["APIUserDep", "make_session_token", "set_session_cookie", "templates"]
```

**3b.** In `src/memlord/ui/login.py`, replace the local `_set_session` function:

Remove lines 22-29 (the `_set_session` function definition).

Update the import from `.utils`:

```python
from .utils import APIUserDep, make_session_token, set_session_cookie, templates
```

Replace all usages of `_set_session(response, ...)` with `set_session_cookie(response, ...)` in `login_post`, `register_post`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_azure_sso.py::test_set_session_cookie_sets_cookie -v`
Expected: 1 passed

**Step 5: Run existing login tests to ensure no regressions**

Run: `pytest tests/test_dao.py tests/test_data.py -v`
Expected: All passed

**Step 6: Commit**

```bash
git add src/memlord/ui/utils.py src/memlord/ui/login.py tests/test_azure_sso.py
git commit -m "refactor: extract _set_session to shared set_session_cookie utility"
```

---

### Task 6: Add `SessionMiddleware` for authlib OAuth state

**Background:** authlib's `authorize_redirect` calls `self.framework.set_state_data(request.session, state, kwargs)` to store OAuth state/nonce. Starlette's `request.session` **requires** `SessionMiddleware` to be installed, otherwise it raises `AssertionError: "SessionMiddleware must be installed to access request.session"`.

**Files:**
- Modify: `src/memlord/main.py:28` (add middleware after `app = FastAPI(...)`)

**Step 1: Write the failing test**

Add to `tests/test_azure_sso.py`:

```python
def test_session_middleware_installed():
    """SessionMiddleware must be present for authlib OAuth state management."""
    from starlette.middleware.sessions import SessionMiddleware
    middlewares = [type(m) for m in app.user_middleware]
    assert SessionMiddleware in middlewares
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_azure_sso.py::test_session_middleware_installed -v`
Expected: FAIL — `AssertionError`

**Step 3: Write the implementation**

In `src/memlord/main.py`, add the import and middleware registration right after `app = FastAPI(...)` (line 28):

```python
from starlette.middleware.sessions import SessionMiddleware

# ...

app = FastAPI(title="Memlord", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.oauth_jwt_secret)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_azure_sso.py::test_session_middleware_installed -v`
Expected: 1 passed

**Step 5: Run full test suite to ensure no regressions**

Run: `pytest tests/ -v`
Expected: All passed (SessionMiddleware should not break existing routes)

**Step 6: Commit**

```bash
git add src/memlord/main.py tests/test_azure_sso.py
git commit -m "feat: add SessionMiddleware for authlib OAuth state management"
```

---

### Task 7: Create `src/memlord/sso.py` — core OIDC module

**Files:**
- Create: `src/memlord/sso.py`
- Test: `tests/test_azure_sso.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_azure_sso.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_azure_sso.py -k "create_azure_router or email_domain" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memlord.sso'`

**Step 3: Write the implementation**

Create `src/memlord/sso.py`:

```python
import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from memlord.config import settings
from memlord.dao.user import UserDao
from memlord.db import APISessionDep
from memlord.ui.utils import set_session_cookie

logger = logging.getLogger(__name__)

_azure_oauth = OAuth()

router = APIRouter()


def _is_email_allowed(email: str, allowed_domains: list[str] | None) -> bool:
    if not allowed_domains:
        return True
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in [d.lower() for d in allowed_domains]


def create_azure_router() -> APIRouter | None:
    if not (
        settings.azure_sso_enabled
        and settings.azure_client_id
        and settings.azure_tenant_id
    ):
        return None

    redirect_uri = settings.azure_redirect_uri
    if not redirect_uri:
        redirect_uri = f"{settings.base_url}/auth/azure/callback"

    _azure_oauth.register(
        name="azure",
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
            f"/v2.0/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": settings.azure_scope},
        redirect_uri=redirect_uri,
    )
    return router


@router.get("/auth/azure/login")
async def azure_login(request: Request):
    redirect_uri = settings.azure_redirect_uri
    if not redirect_uri:
        redirect_uri = f"{settings.base_url}/auth/azure/callback"
    return await _azure_oauth.azure.authorize_redirect(request, redirect_uri)


@router.get("/auth/azure/callback")
async def azure_callback(request: Request, s: APISessionDep):
    try:
        token = await _azure_oauth.azure.authorize_access_token(request)
    except Exception:
        logger.warning("Azure SSO: token exchange failed", exc_info=True)
        return RedirectResponse("/ui/login?error=azure_failed", status_code=303)

    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await _azure_oauth.azure.userinfo(token=token)

    email = userinfo.get("email", "").strip().lower()
    if not email:
        logger.warning("Azure SSO: no email in user info")
        return RedirectResponse("/ui/login?error=azure_failed", status_code=303)

    sub = userinfo.get("sub", "")
    name = userinfo.get("name", email)

    if not _is_email_allowed(email, settings.azure_allowed_email_domains):
        return RedirectResponse("/ui/login?error=azure_denied", status_code=303)

    user = await UserDao(s).get_or_create_by_email_for_sso(
        email=email,
        display_name=name,
        azure_sub=sub,
        auto_register=settings.azure_auto_register,
    )

    if user is None:
        return RedirectResponse("/ui/login?error=azure_no_account", status_code=303)

    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, user.id)
    return response
```

Key points about the implementation:
- Uses `APISessionDep` (project convention for UI/API routes), not raw `session_dep`
- Uses `set_session_cookie` from `ui/utils.py` (no duplication)
- `create_azure_router()` takes no parameters — authlib's `OAuth()` doesn't need the app reference
- Uses `token.get("userinfo")` first (authlib populates this from id_token during OIDC flow), falls back to `userinfo(token=token)` to fetch from Azure's userinfo endpoint if missing

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_azure_sso.py -k "create_azure_router or email_domain" -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/memlord/sso.py tests/test_azure_sso.py
git commit -m "feat: add Azure SSO OIDC module with login and callback routes"
```

---

### Task 8: Register Azure router in main.py

**Files:**
- Modify: `src/memlord/main.py:65-67`

**Step 1: Add the router registration**

In `src/memlord/main.py`, add the Azure router registration right before the existing `app.include_router(ui_router)` line:

```python
if settings.azure_sso_enabled and settings.azure_client_id and settings.azure_tenant_id:
    from memlord.sso import create_azure_router
    azure_router = create_azure_router()
    if azure_router:
        app.include_router(azure_router)
```

Note: no tests needed here — `create_azure_router()` returning `None` when not configured is already tested in Task 7. Route registration is a one-line conditional that's covered by the UI template tests in Task 9.

**Step 2: Commit**

```bash
git add src/memlord/main.py
git commit -m "feat: conditionally register Azure SSO router in main.py"
```

---

### Task 9: Update login page template and login routes

**Files:**
- Modify: `src/memlord/templates/login.html`
- Modify: `src/memlord/ui/login.py:32-34` (login_get handler)
- Modify: `src/memlord/ui/login.py:67-69` (register_get handler)
- Modify: `src/memlord/ui/login.py:72-81` (register_post handler)
- Test: `tests/test_azure_sso.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_azure_sso.py`:

```python
from memlord.main import app
from starlette.testclient import TestClient


async def test_login_page_shows_azure_button_when_enabled(monkeypatch):
    """When Azure SSO is enabled, login page should contain Azure button."""
    monkeypatch.setattr("memlord.ui.login.settings", type("obj", (), {
        "azure_sso_enabled": True,
        "azure_login_button_text": "Sign in with Azure AD",
        "local_password_login_enabled": True,
        "local_registration_enabled": True,
    })())
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
    client = TestClient(app)
    resp = client.get("/ui/login")
    assert resp.status_code == 200
    assert "SSO" in resp.text
    assert 'type="password"' not in resp.text


async def test_register_page_redirects_when_disabled(monkeypatch):
    """When local_registration_enabled=False, GET /ui/register should redirect to login."""
    monkeypatch.setattr("memlord.ui.login.settings", type("obj", (), {
        "azure_sso_enabled": False,
        "azure_login_button_text": "SSO",
        "local_password_login_enabled": True,
        "local_registration_enabled": False,
    })())
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
    client = TestClient(app)
    resp = client.get("/ui/login")
    assert resp.status_code == 200
    assert "Create one" not in resp.text
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_azure_sso.py -k "login_page" -v`
Expected: FAIL — Azure button not found in HTML

**Step 3: Write the implementation**

**3a.** Update `src/memlord/ui/login.py` — `login_get` to pass new template variables:

```python
@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, next: str = "/") -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {
        "next": next,
        "azure_sso_enabled": settings.azure_sso_enabled,
        "azure_login_button_text": settings.azure_login_button_text,
        "local_password_login_enabled": settings.local_password_login_enabled,
        "local_registration_enabled": settings.local_registration_enabled,
    })
```

Update `register_get` to check `settings.local_registration_enabled` and redirect to login if disabled:

```python
@router.get("/register", response_class=HTMLResponse)
async def register_get(request: Request, next: str = "/") -> Response:
    if not settings.local_registration_enabled:
        return RedirectResponse("/ui/login", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"next": next})
```

Add the guard at the top of `register_post` (before the `_err` function definition):

```python
@router.post("/register")
async def register_post(
    request: Request,
    s: APISessionDep,
    email: EmailStr = Form(),
    display_name: str = Form(min_length=3),
    password: str = Form(min_length=6),
    password2: str = Form(min_length=6),
    next: str = Form(default="/"),
) -> Response:
    if not settings.local_registration_enabled:
        return RedirectResponse("/ui/login", status_code=303)
    # ... rest unchanged
```

Also update `login_post` to pass the Azure toggle variables when rendering the error response (so the Azure button still shows on error):

In the error path of `login_post`, update the `TemplateResponse` call to include the extra variables:

```python
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "next": next,
                "error": "Incorrect email or password.",
                "azure_sso_enabled": settings.azure_sso_enabled,
                "azure_login_button_text": settings.azure_login_button_text,
                "local_password_login_enabled": settings.local_password_login_enabled,
                "local_registration_enabled": settings.local_registration_enabled,
            },
            status_code=401,
        )
```

**3b.** Update `src/memlord/templates/login.html` — replace the entire content inside `.login-card` with:

```html
    <div class="login-card">
        {% if azure_sso_enabled %}
        <a href="/auth/azure/login" class="btn-azure">
            <svg width="20" height="20" viewBox="0 0 23 23" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M0 0h11v11H0zM12 0h11v11H12zM0 12h11v11H0zM12 12h11v11H12z" fill="#f25022"/>
            </svg>
            {{ azure_login_button_text }}
        </a>
        {% endif %}
        {% if azure_sso_enabled and local_password_login_enabled %}
        <div class="sso-divider"><span>or</span></div>
        {% endif %}
        {% if local_password_login_enabled %}
        <div class="login-heading">Sign in</div>
        <div class="login-subheading">Enter your email and password to continue.</div>
        <form method="post" action="/ui/login">
            <input type="hidden" name="next" value="{{ next }}">
            <div class="form-group">
                <label for="email">Email</label>
                <input type="email" id="email" name="email" autofocus required autocomplete="email">
            </div>
            <div class="form-group">
                <label for="pw">Password</label>
                <input type="password" id="pw" name="password" required autocomplete="current-password">
            </div>
            <button type="submit" class="btn-submit">Sign in</button>
            {% if error %}<p class="error">{{ error }}</p>{% endif %}
            {% if request.query_params.get('reset') %}<p style="margin-top:.875rem;padding:.625rem .875rem;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;color:#16a34a;font-size:.8125rem;">Password updated — you can now sign in.</p>{% endif %}
        </form>
        {% if smtp_configured %}<p class="register-link" style="margin-top:.625rem;"><a href="/ui/forgot-password" style="color:#8b8fa8;font-size:.8125rem;">Forgot password?</a></p>{% endif %}
        {% endif %}
        {% if local_password_login_enabled and local_registration_enabled %}
        <p class="register-link">No account? <a href="/ui/register?next={{ next }}">Create one</a></p>
        {% endif %}
        {% if request.query_params.get('error') == 'azure_failed' %}
        <p class="error">Azure SSO authentication failed. Please try again.</p>
        {% elif request.query_params.get('error') == 'azure_no_account' %}
        <p class="error">Your account is not registered. Please contact your administrator.</p>
        {% elif request.query_params.get('error') == 'azure_denied' %}
        <p class="error">Access denied. Your email domain is not allowed.</p>
        {% elif not azure_sso_enabled and not local_password_login_enabled %}
        <p class="error">No login method is configured. Please contact your administrator.</p>
        {% endif %}
    </div>
```

Add CSS for the Azure button and divider (add inside the existing `<style>` block, before `</style>`):

```css
        .btn-azure { display: flex; align-items: center; justify-content: center; gap: 0.625rem;
            width: 100%; margin-bottom: 1rem; padding: 0.625rem; background: #fff;
            border: 1px solid #d1d5db; border-radius: 6px; color: #333;
            font-size: 0.875rem; font-family: inherit; font-weight: 500;
            cursor: pointer; text-decoration: none; transition: background .12s; }
        .btn-azure:hover { background: #f3f4f6; }
        .sso-divider { display: flex; align-items: center; margin-bottom: 1.25rem;
            color: #8b8fa8; font-size: 0.8125rem; }
        .sso-divider::before, .sso-divider::after { content: ''; flex: 1; height: 1px; background: #1f1f38; }
        .sso-divider span { padding: 0 0.75rem; }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_azure_sso.py -k "login_page" -v`
Expected: 4 passed

**Step 5: Run full test suite to ensure no regressions**

Run: `pytest tests/test_dao.py tests/test_data.py tests/test_api_key.py -v`
Expected: All passed

**Step 6: Commit**

```bash
git add src/memlord/ui/login.py src/memlord/templates/login.html tests/test_azure_sso.py
git commit -m "feat: update login page with Azure SSO button and auth toggle controls"
```

---

### Task 10: Run full test suite and type check

**Step 1: Run all tests**

Run: `pytest -v`
Expected: All passed

**Step 2: Run type check**

Run: `pyright src/`
Expected: No new errors

**Step 3: Run format check**

Run: `black --check .`
Expected: No formatting issues

**Step 4: Run alembic-autogen-check**

Run: `alembic-autogen-check`
Expected: Models and migrations are in sync

**Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: resolve type/format/migration issues from Azure SSO implementation"
```
