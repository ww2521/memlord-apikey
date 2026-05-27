# Azure AD SSO Integration — Design Document

> Date: 2026-05-27 | Status: Approved

## 1. Overview

Add Azure AD (Entra ID) as an external OIDC identity provider, allowing users to log into Memlord's Web UI via corporate SSO. The existing OAuth 2.1 Authorization Server (for MCP clients) and local password auth remain unchanged.

**Scope:** Azure AD only (not a generic OIDC abstraction). Future providers can be added later with minimal refactoring.

---

## 2. Configuration

All new settings use the `MEMLORD_AZURE_` prefix, consistent with the existing `MEMLORD_*` convention.

| Variable | Type | Default | Description |
|---|---|---|---|
| `MEMLORD_AZURE_SSO_ENABLED` | `bool` | `false` | Master switch. Routes and UI button only appear when `true`. |
| `MEMLORD_AZURE_CLIENT_ID` | `str \| None` | `None` | Azure App Registration client ID. |
| `MEMLORD_AZURE_CLIENT_SECRET` | `str \| None` | `None` | Azure client secret (stored in `.env`, never committed). |
| `MEMLORD_AZURE_TENANT_ID` | `str \| None` | `None` | Azure Directory (tenant) ID. |
| `MEMLORD_AZURE_REDIRECT_URI` | `str \| None` | `None` | Callback URL. Defaults to `{MEMLORD_BASE_URL}/auth/azure/callback`. |
| `MEMLORD_AZURE_SCOPE` | `str` | `"openid profile email"` | OIDC scopes requested from Azure. |
| `MEMLORD_AZURE_LOGIN_BUTTON_TEXT` | `str` | `"Sign in with Azure AD"` | Text displayed on the SSO login button. |
| `MEMLORD_AZURE_ALLOWED_EMAIL_DOMAINS` | `list[str] \| None` | `None` | Optional email domain whitelist (comma-separated). |
| `MEMLORD_AZURE_AUTO_REGISTER` | `bool` | `true` | Auto-create Memlord user on first SSO login. |
| `MEMLORD_LOCAL_PASSWORD_LOGIN_ENABLED` | `bool` | `true` | Show the email+password login form. |
| `MEMLORD_LOCAL_REGISTRATION_ENABLED` | `bool` | `true` | Show the registration link on the login page. |

**Activation logic:** Azure SSO routes are registered only when `azure_sso_enabled=True` AND `azure_client_id` AND `azure_tenant_id` are all set.

---

## 3. Database Changes

### 3.1 `users` table

```sql
ALTER TABLE users ADD COLUMN azure_sub VARCHAR(255) UNIQUE;
ALTER TABLE users ADD COLUMN auth_method VARCHAR(32) NOT NULL DEFAULT 'local';
ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;
```

| Column | Type | Nullable | Description |
|---|---|---|---|
| `azure_sub` | `VARCHAR(255)` | Yes, UNIQUE | Azure AD `sub` claim. Links an external identity to a local user. |
| `auth_method` | `VARCHAR(32)` | No | `'local'` (password login) or `'azure_sso'`. Informational only. |
| `hashed_password` | `TEXT` | **Yes** (changed from NOT NULL) | SSO users have no password. |

### 3.2 User matching logic

On Azure callback, given `email`, `name`, and `sub` from the id_token:

1. Look up user by `email` (case-insensitive, normalized to lowercase).
2. **Found** — update `azure_sub` if currently NULL, return existing user.
3. **Not found** — if `azure_auto_register=True`, create new user with `azure_sub=sub`, `auth_method='azure_sso'`, `hashed_password=NULL`. `UserDao.create()` handles personal workspace creation automatically.
4. **Not found, auto-register disabled** — reject with a friendly error message ("Contact your administrator to create an account").

---

## 4. Core Flow: `src/memlord/sso.py`

New file, approximately 120 lines.

### 4.1 Dependencies

- `authlib.integrations.starlette_client.OAuth` — handles OIDC redirect, token exchange, id_token parsing, and nonce/state management automatically.

### 4.2 Module structure

```python
# Module-level OAuth instance
_azure_oauth = OAuth()

def create_azure_router(app: FastAPI) -> APIRouter | None:
    """Called from main.py at startup. Returns APIRouter with login/callback routes,
    or None if Azure SSO is not configured."""

@router.get("/auth/azure/login")
async def azure_login(request: Request):
    """Redirect to Azure AD authorize endpoint. Authlib manages state/nonce."""

@router.get("/auth/azure/callback")
async def azure_callback(request: Request):
    """Handle Azure callback:
    1. Exchange authorization code for token (authlib automatic)
    2. Parse id_token → email, sub, name
    3. Validate email domain whitelist (if configured)
    4. Find or create Memlord user
    5. Issue session token via make_session_token()
    6. Set memlord_session cookie
    7. Redirect to home page"""
```

### 4.3 Integration with existing session mechanism

The callback reuses the same session mechanism as the existing password login in `ui/login.py`:

- `make_session_token(user_id)` from `memlord.ui.utils` — creates HMAC-signed session token
- `memlord_session` cookie with 30-day TTL
- Identical to what `POST /login` does today

### 4.4 Error handling

| Error | Response |
|---|---|
| Azure config incomplete | Routes not registered (silent skip) |
| Email domain not in whitelist | 403 page with access denied message |
| Token exchange failure | Redirect to `/login?error=azure_failed` |
| User not found + auto-register disabled | Redirect to `/login?error=azure_no_account` |

---

## 5. Route Registration (`main.py`)

```python
# In create_app(), before ui_router registration:
if settings.azure_sso_enabled and settings.azure_client_id and settings.azure_tenant_id:
    from memlord.sso import create_azure_router
    azure_router = create_azure_router(app)
    if azure_router:
        app.include_router(azure_router)
```

Registered before `ui_router` so `/auth/azure/*` routes take priority.

---

## 6. UI Changes

### 6.1 Login page template

The login template receives two new context variables: `azure_sso_enabled` and `azure_login_button_text`.

```
{% if azure_sso_enabled %}
  [Azure login button — text from config]
  {% if local_password_login_enabled %}
    — divider —
    [email + password form]
    {% if local_registration_enabled %}
      [register link]
    {% endif %}
  {% endif %}
{% elif local_password_login_enabled %}
  [email + password form]  ← existing behavior
  {% if local_registration_enabled %}
    [register link]
  {% endif %}
{% endif %}
```

Supported configurations:

| `azure_sso_enabled` | `local_password_login_enabled` | `local_registration_enabled` | Result |
|---|---|---|---|
| `true` | `true` | `true` | Both login methods + registration (default future state) |
| `true` | `true` | `false` | Both login methods, no self-registration |
| `true` | `false` | * | SSO only |
| `false` | `true` | `true` | Password only (current default) |
| `false` | `false` | * | No login method (misconfiguration, should be prevented) |

### 6.2 Logout

SSO users use the same `/logout` endpoint. This clears the local `memlord_session` cookie. It does **not** perform Azure AD logout (single logout is out of scope).

---

## 7. Files Changed

| File | Change |
|---|---|
| `src/memlord/sso.py` | **New** — OIDC client, login/callback routes (~120 lines) |
| `src/memlord/config.py` | Add 10 new `MEMLORD_AZURE_*` + `MEMLORD_LOCAL_*` fields |
| `src/memlord/models/user.py` | Add `azure_sub`, `auth_method` columns; `hashed_password` nullable |
| `src/memlord/dao/user.py` | Add `get_or_create_by_email_for_sso()` method |
| `src/memlord/main.py` | Conditional registration of azure_router (~5 lines) |
| `src/memlord/ui/login.py` | Pass `azure_sso_enabled` + `azure_login_button_text` to template; respect `local_registration_enabled` |
| `migrations/versions/xxx_azure_sso.py` | **New** — Alembic migration for user table changes |

---

## 8. Security Considerations

- **State/Nonce**: Handled automatically by authlib's Starlette integration. Prevents CSRF and replay attacks.
- **ID Token validation**: Authlib verifies `iss`, `aud`, `exp`, and `nonce` claims. We do not trust unverified tokens.
- **Client secret**: Stored in `.env`, never committed to git, never logged.
- **Email whitelist**: Optional `MEMLORD_AZURE_ALLOWED_EMAIL_DOMAINS` restricts access to approved domains.
- **HTTPS**: Required in production for redirect URIs and token transport.

---

## 9. Out of Scope

- Generic OIDC provider abstraction (future work)
- Azure AD group synchronization / workspace mapping
- SCIM user provisioning
- SAML support
- Single logout (Azure AD session remains active after Memlord logout)
- API key issuance via SSO (API keys use a separate auth path)
