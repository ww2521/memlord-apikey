# Reverse Proxy Subpath (root_path) Support

> 2026-05-28

## Goal

Support deploying Memlord under a reverse proxy subpath (e.g. `example.com/memlord`) via `MEMLORD_ROOT_PATH` env var. Fully backward compatible — default `root_path=""` means root deployment.

## Key Decisions

1. **Always-use root_router** — `APIRouter(prefix=root_prefix)` wraps all routes unconditionally. `prefix=""` is a no-op, so no duplicated route handlers needed.
2. **Mount at `{root_prefix}/`** — `mcp_app` contains not just `/mcp` but also OAuth routes (`/.well-known/*`, `/authorize`, `/token`, `/login`). Mounting at `{root_prefix}/` strips the prefix before passing to `mcp_app`, so its internal routes don't need prefixing.
3. **Startup validation** — when both `base_url` and `root_path` are set, assert `base_url.endswith(root_path)`.
4. **`settings.base_url` over `request.base_url`** — for invite URLs, since `request.base_url` is affected by proxy config.
5. **No `get_routes()` prefixing needed** — the mount strips `root_prefix` before `mcp_app` sees the path, so OAuth routes inside `mcp_app` remain at their original paths. Only URL string constructions (login_url, audience) need `root_path`.

## Changes

### 1. `config.py` — Add `root_path`

```python
root_path: str = ""  # reverse proxy path prefix, e.g. "/memlord"
```

Add startup validator: if `root_path` and `base_url` are both set, `base_url` must end with `root_path`.

### 2. `main.py` — root_router wrapper

- Create `root_router = APIRouter(prefix=settings.root_path.rstrip("/"))` always
- Include `api_router`, `azure_router` (conditional), `ui_router` under `root_router`
- Register `/health`, `/favicon.png`, `/favicon.svg` on `root_router` (not `app`)
- Mount: `app.mount(f"{root_prefix}/", mcp_app)` — strips the subpath prefix before passing to `mcp_app`, so OAuth routes (`/.well-known/*`, `/authorize`, `/token`, `/login`) work without modification
- Inject `root_path` into Jinja globals: `templates.env.globals["root_path"] = root_prefix`

No duplicated handlers. Root deployment (`root_path=""`) and subpath deployment use identical code paths.

### 3. `oauth.py` — No changes needed

`authorize()` already uses `self._base_url` which includes the subpath (enforced by validation), so `f"{self._base_url}/login"` produces the correct URL. `set_mcp_path()` similarly uses `_resource_url` / `_base_url`. The mount handles all route prefixing.

### 4. `server.py` — No changes needed

No `root_path` to pass to `MemlordOAuthProvider`.

### 5. `sso.py` — Azure SSO redirects

All `RedirectResponse` calls prepend `settings.root_path.rstrip("/")`:
- `/ui/login?error=...` (4 places: `azure_failed` x2, `azure_denied`, `azure_no_account`)
- `/` (1 place)

Azure callback URL construction unchanged (uses `settings.base_url`).

### 6. `ui/login.py` — Login/redirect handling

- All `RedirectResponse` paths prepend `root_path`
- `_safe_redirect()`: default return `f"{rp}/"` instead of `"/"`
- `next` parameter: default to `f"{rp}/"` in function body (not `Form(default=...)` which is evaluated at import time)
- `logout`: use `delete_session_cookie(response)` from `utils.py` instead of bare `response.delete_cookie("memlord_session")`

### 7. `ui/utils.py` — Cookie and auth guard

- `set_session_cookie`: set `path=f"{rp}/"` on cookie
- Add `delete_session_cookie(response)`: wraps `response.delete_cookie("memlord_session", path=f"{rp}/")` so logout removes the cookie at the same path it was set
- `require_auth`: redirect to `f"{rp}/ui/login?next=..."`

### 8. `api/workspaces.py` — Invite URL

Replace `request.base_url` with `settings.base_url` for invite URL construction.

**Static HTML:**
- `href="/xxx"` → `href="{{ root_path }}/xxx"`
- `href="/"` → `href="{{ root_path or '/' }}"`
- `action="/xxx"` → `action="{{ root_path }}/xxx"`
- `src="/favicon.svg"` → `src="{{ root_path }}/favicon.svg"`

**Dynamic JS (in `<script>` blocks):**
- `fetch('/api/...')` → `fetch(rootPath + '/api/...')`
- `window.location.href = '/xxx'` → `window.location.href = rootPath + '/xxx'`
- `window.location.href = '/'` → `window.location.href = rootPath || '/'`
- `:href="'/xxx'"` → `:href="rootPath + '/xxx'"`

**JS variable injection** in `base.html` `<head>`:
```html
<script>var rootPath = "{{ root_path }}";</script>
```

**Templates affected (16 files):**
base.html, login.html, register.html, forgot_password.html, reset_password.html, index.html, memory.html, search.html, workspaces.html, workspace_new.html, workspace_detail.html, workspace_join.html, verify_email.html, settings.html

## Not Changed

- `api/memories.py`, `api/search.py` — wrapped by `api_router` which is under `root_router`
- `ui/workspaces.py`, `ui/api_keys.py`, `ui/base.py` — wrapped by `ui_router`
- `auth.py`, `dao/*`, `models/*`, `schemas/*` — data layer, no HTTP paths
- `embeddings.py`, `search.py`, `db.py` — pure logic
- `tools/*` — MCP tool implementations
- `utils/mail_send.py` — mail URLs passed by caller (caller uses `settings.base_url` which already includes subpath)
- `utils/inject_client_id.py` — mount strips prefix, internal path stays `/token`
- `oauth.py` — `authorize()` and `set_mcp_path()` already use `_base_url` which includes subpath; mount handles route prefixing. No changes needed.
- `server.py` — no `root_path` to pass to `MemlordOAuthProvider`. No changes needed.
- `ui/login.py` email body URLs (verify-email, reset-password) — already use `settings.base_url` which includes subpath

## Config Example

```env
MEMLORD_BASE_URL=https://example.com/memlord
MEMLORD_ROOT_PATH=/memlord
```
