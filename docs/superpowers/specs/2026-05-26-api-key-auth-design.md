# API Key Authentication for MCP Service

## Goal

Allow users to create API keys via the web UI and use them as bearer tokens when connecting MCP clients in HTTP mode. API key auth coexists with the existing OAuth 2.1 flow — OAuth remains for Claude Desktop, API keys are the simpler path for agents and scripts.

## Auth Method Relationship

| | OAuth 2.1 | API Key |
|---|---|---|
| How client gets it | Browser redirect → login → code exchange → access token | Copy/paste from web UI |
| Best for | Claude Desktop, OAuth-native apps | Scripts, agents, Claude Code |
| Transport | HTTPS required | Works over HTTP |
| Token lifecycle | Short-lived, auto-refreshed | Long-lived, manually rotated |

Both methods pass through FastMCP's `Authorization: Bearer` header path. The server resolves them at the same chokepoint.

## Database Schema

New table `api_keys`:

```sql
CREATE TABLE api_keys (
    id           SERIAL PRIMARY KEY,
    user_id      INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         VARCHAR(100) NOT NULL,
    key_hash     VARCHAR(64) NOT NULL,     -- SHA-256 of raw key
    prefix       VARCHAR(12) NOT NULL,     -- first 12 chars, for display
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    UNIQUE (user_id, name)
);
CREATE INDEX ix_api_keys_key_hash ON api_keys (key_hash);
```

**Key format:** `mlk_<32 random URL-safe chars>` (~37 chars total). The raw key is shown to the user once on creation. Only `key_hash` and `prefix` are stored.

**Per-user cap:** 5 keys maximum, enforced at the application layer.

## Auth Resolution Flow

When an MCP client sends `Authorization: Bearer <token>`:

1. FastMCP's auth middleware calls `load_access_token(token)` on `MemlordOAuthProvider`
2. **JWT path (existing):** Verify token as a JWT. If valid, return `AccessToken` with `client_id` from claims.
3. **API key path (new):** If JWT fails and token starts with `mlk_`, SHA-256 hash it and look up in `api_keys` table. If found, return an `AccessToken` with `client_id` set to `"api_key:<id>"` (synthetic client_id).
4. **Neither:** Return `None` → auth fails (401).

`_current_user_gen` in `auth.py` is updated:
- If `client_id` starts with `"api_key:"`, extract the key `id`, look up `user_id` from `api_keys.id`
- Otherwise, fall through to existing OAuth client_id lookup
- Update `last_used_at` on successful API key auth

`_current_user_gen` remains the single chokepoint — all MCP tools continue to receive `user_id` identically.

## Web UI — API Key Management

New page at `/ui/settings` with:

**List keys:** Table showing name, prefix (`mlk_a1b2...`), created date, last used date, and a revoke button.

**Create key:** Form with a name field. On submit, generate key, display the full raw key once in a copyable field with a warning that it will not be shown again.

**Revoke key:** Confirmation dialog, then hard delete from DB.

Page protected by existing `APIUserDep` (session-based auth). Add "Settings" link to existing UI navigation.

## File Changes

| File | Change |
|---|---|
| `models/api_key.py` | New — `api_keys` table definition |
| `models/__init__.py` | Re-export new model |
| `schemas/api_key.py` | New — `ApiKeyInfo`, `ApiKeyCreate` Pydantic schemas |
| `schemas/__init__.py` | Re-export new schemas |
| `dao/api_key.py` | New — `ApiKeyDao` with `create`, `list_by_user`, `delete`, `validate_key` methods |
| `oauth.py` | Extend `load_access_token()` to handle `mlk_` prefixed tokens |
| `auth.py` | Extend `_current_user_gen` to resolve `api_key:<id>` synthetic client_id |
| `ui/__init__.py` | Add api-keys sub-router |
| `ui/api_keys.py` | New — settings page routes: list, create, revoke |
| `templates/settings.html` | New — HTML template for API key management |
| Navigation template | Add "Settings" link |
| Alembic migration | New — create `api_keys` table |

**No changes** to MCP tools, existing DAOs, or existing OAuth flows.

## Out of Scope

- Per-workspace key scoping (keys inherit all user permissions)
- Key expiration / auto-rotation
- Audit logging of API key usage
- Certified shared memory permissions (existing workspace owner role already handles this)
