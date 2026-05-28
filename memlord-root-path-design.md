# Memlord 支持反向代理子路径部署 — 设计文档

> 版本: v0.4 | 2026-05-28 | 作者: Dee

---

## 1. 背景与目标

### 1.1 现状

Memlord 的所有路由都挂载在根路径 `/` 下，无法部署在反向代理的子路径（如 `example.com/memlord`）。

已有的 `MEMLORD_BASE_URL` 环境变量仅用于拼接 OAuth issuer、回调地址和邮件链接中的**完整 URL**，不参与路由匹配。

### 1.2 目标

支持通过环境变量 `MEMLORD_ROOT_PATH` 配置路径前缀，使 Memlord 可以部署在反向代理的子路径下，同时兼容现有的根路径部署（默认 `root_path=""`）。

---

## 2. 配置变更

### `config.py` — 新增 `root_path`

```python
root_path: str = ""   # 反向代理路径前缀，如 "/memlord"，默认空（根路径部署）
```

| 变量 | 用途 | 示例值 |
|---|---|---|
| `root_path` | 服务内部路由前缀，用于路由匹配、cookie path | `/memlord` |
| `base_url` | 对外完整公开 URL，用于拼 issuer、回调地址、邮件链接 | `https://example.com/memlord` |

**两者关系：** `base_url = "https://example.com" + root_path`

> 注意：不能从 `base_url` 解析出 `root_path`（域名是外部配置的），必须独立配置。

---

## 3. 核心架构设计

### 3.1 路由策略：root_router 包裹 + mount 兜底

**关键问题：** `main.py` 中 `app.mount()` 在 `include_router` 之后注册。`include_router` 的路由注册在 `app` 上，路径是 `/ui/...`、`/api/...`。如果直接 `app.mount("/memlord/", mcp_app)`，访问 `/memlord/ui/login` 时 `app` 先匹配——但 `app` 上没有 `/memlord/ui/login` 路由（只有 `/ui/login`），匹配失败交给 mount，mount 剥离 `/memlord` 传给 `mcp_app`，mcp_app 也没有 `/ui/login` → 404。

**解决方案：** 用一个带 `prefix` 的 `root_router` 包裹所有 `include_router`：

```python
root_prefix = settings.root_path.rstrip("/")
root_router = APIRouter(prefix=root_prefix) if root_prefix else None

if root_router:
    root_router.include_router(api_router)
    root_router.include_router(azure_router)  # SSO
    root_router.include_router(ui_router)
    app.include_router(root_router)
else:
    app.include_router(api_router)
    app.include_router(azure_router)
    app.include_router(ui_router)
```

### 3.2 /health、/favicon 和 /static 路由处理

当前 `main.py` 直接注册在 `app` 上：
```python
@app.get("/health")
@app.get("/favicon.png")
@app.get("/favicon.svg")
```

**问题：** subpath 下用户访问 `/memlord/health`，`app` 匹配失败后交给 mount → mcp_app 没有 `/health` → 404。

**解决方案：** 在 `root_router` 上也注册这些路由。两套共存：`app.get()` 给根路径部署用，`root_router.get()` 给 subpath 部署用。

### 3.3 静态文件 `/favicon.svg` 的 `<img src>` 问题

`base.html` 中：
```html
<img src="/favicon.svg" class="nav-brand-icon" alt="Memlord">
```

subpath 下 `/favicon.svg` 变成绝对路径请求 `https://example.com/favicon.svg`，不是 `https://example.com/memlord/favicon.svg`。

**解决方案：** 模板中替换为 `<img src="{{ root_path }}/favicon.svg">`（根路径下是 `/favicon.svg`）。

---

## 4. 涉及模块

### 4.1 需要改动的模块

| 文件 | 改动类型 | 改动点数 |
|---|---|---|
| `src/memlord/config.py` | 新增配置项 | 1 |
| `src/memlord/main.py` | root_router 包裹 + health/favicon + 模板注入 | 5 |
| `src/memlord/oauth.py` | OAuth 路由前缀 + login_url + set_mcp_path | 4 |
| `src/memlord/server.py` | 透传 root_path 给 MemlordOAuthProvider | 1 |
| `src/memlord/utils/inject_client_id.py` | 不需要改（mount 剥离后内部路径仍是 `/token`） | 0 |
| `src/memlord/sso.py` | RedirectResponse 路径前缀 | 6 |
| `src/memlord/ui/base.py` | 不需要改（被 root_router 自动加前缀） | 0 |
| `src/memlord/ui/login.py` | RedirectResponse + _safe_redirect + next 默认值 | 11 |
| `src/memlord/ui/utils.py` | auth guard redirect + cookie path | 2 |
| `src/memlord/api/workspaces.py` | invite URL 中 `request.base_url` 需要加 root_path | 1 |
| `src/memlord/templates/*.html` | 静态 HTML + 动态 JS 路径 + img src | ~61 |

### 4.2 不需要改动的模块

| 模块 | 原因 |
|---|---|
| `api/memories.py`、`api/search.py` | 通过 `APIRouter(prefix=...)` 注册，会被 root_router 包裹 |
| `api/__init__.py` | `APIRouter(prefix="/api")`，同上 |
| `ui/__init__.py` | `APIRouter(prefix="/ui")`，同上 |
| `ui/workspaces.py`、`ui/api_keys.py`、`ui/base.py` | 同上 |
| `auth.py`、`dao/*`、`models/*`、`schemas/*` | 纯数据层 |
| `embeddings.py`、`search.py`、`db.py` | 纯逻辑层 |
| `tools/*` | MCP tool 实现，不处理 HTTP |
| `utils/mail_send.py` | 邮件 URL 由调用方传入 `base_url` 拼接 |

---

## 5. 详细设计

### 5.1 `config.py`

```python
root_path: str = ""  # 反向代理路径前缀，如 "/memlord"
```

### 5.2 `main.py` — 启动层

#### 改动点 1：root_router 包裹所有 include_router

```python
root_prefix = settings.root_path.rstrip("/")
root_router = APIRouter(prefix=root_prefix) if root_prefix else None

# UI and API routes must be registered BEFORE the root mount
if root_router:
    root_router.include_router(api_router)
    if settings.azure_sso_enabled and settings.azure_client_id and settings.azure_tenant_id:
        from memlord.sso import create_azure_router
        azure_r = create_azure_router()
        if azure_r:
            root_router.include_router(azure_r)
    root_router.include_router(ui_router)
    app.include_router(root_router)
else:
    app.include_router(api_router)
    if settings.azure_sso_enabled and settings.azure_client_id and settings.azure_tenant_id:
        from memlord.sso import create_azure_router
        azure_r = create_azure_router()
        if azure_r:
            app.include_router(azure_r)
    app.include_router(ui_router)
```

#### 改动点 2：health/favicon 路由注册两套

```python
# Root-level routes (for root_path="" deployment)
@app.get("/favicon.png", include_in_schema=False)
async def favicon_png() -> FileResponse:
    return FileResponse(_TEMPLATES / "icon.png", media_type="image/png")

@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg() -> FileResponse:
    return FileResponse(_TEMPLATES / "icon.svg", media_type="image/svg+xml")

@app.get("/health")
async def health() -> JSONResponse:
    try:
        async with session() as s:
            await s.execute(sa.text("SELECT 1"))
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

# Subpath-level routes (for root_path!="" deployment)
if root_router:
    @root_router.get("/favicon.png", include_in_schema=False)
    async def favicon_png_sub() -> FileResponse:
        return FileResponse(_TEMPLATES / "icon.png", media_type="image/png")

    @root_router.get("/favicon.svg", include_in_schema=False)
    async def favicon_svg_sub() -> FileResponse:
        return FileResponse(_TEMPLATES / "icon.svg", media_type="image/svg+xml")

    @root_router.get("/health")
    async def health_sub() -> JSONResponse:
        try:
            async with session() as s:
                await s.execute(sa.text("SELECT 1"))
            return JSONResponse({"status": "ok"})
        except Exception as exc:
            return JSONResponse(
                {"status": "error", "detail": str(exc)},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
```

> 函数名必须不同，否则 Python 会覆盖定义。

#### 改动点 3：mount 策略

```python
root_prefix = settings.root_path.rstrip("/")
app.mount(f"{root_prefix}/", mcp_app)
```

> mount 剥离 `{root_prefix}/` 前缀后传给 mcp_app，mcp_app 内部路径不需要加前缀。

#### 改动点 4：mcp_app 路径

```python
mcp_app = mcp.http_app(path="/mcp")  # 不加 root_path 前缀
```

#### 改动点 5：模板引擎注入 root_path

```python
from memlord.ui.utils import templates
rp = settings.root_path.rstrip("/")
templates.env.globals["root_path"] = rp
```

### 5.3 `oauth.py` — OAuth 2.1 Authorization Server

#### 改动点 1：构造函数接收 `root_path`

```python
def __init__(self, base_url: str, jwt_secret: str, session_factory, root_path: str = ""):
    ...
    self._base_url = base_url.rstrip("/")
    self._root_path = root_path.rstrip("/") if root_path else ""
```

#### 改动点 2：`get_routes()` 所有路由加前缀

```python
def get_routes(self, mcp_path: str | None = None) -> list[Route]:
    routes = super().get_routes(mcp_path)
    if self._root_path:
        routes = [
            Route(path=f"{self._root_path}{r.path}", endpoint=r.endpoint,
                  methods=getattr(r, "methods", None),
                  include_in_schema=getattr(r, "include_in_schema", True))
            for r in routes
        ]
    routes += [Route(path=f"{self._root_path}/login",
                     endpoint=self._login, methods=["GET", "POST"])]
    for route in list(routes):
        if isinstance(route, Route) and route.path.startswith(
                f"{self._root_path}/.well-known/oauth-protected-resource/"):
            routes.append(Route(
                path=f"{self._root_path}/.well-known/oauth-protected-resource",
                endpoint=route.endpoint, methods=["GET", "OPTIONS"]))
            break
    return routes
```

#### 改动点 3：`authorize()` login_url 拼接

```python
login_url = f"{self._base_url}{self._root_path}/login?{urlencode({'id': pending_id})}"
```

#### 改动点 4：`set_mcp_path` 适配

```python
def set_mcp_path(self, mcp_path: str | None) -> None:
    super().set_mcp_path(mcp_path)
    full_mcp_path = f"{self._root_path}{mcp_path}" if mcp_path else self._root_path
    audience = (str(self._resource_url).rstrip("/")
                if self._resource_url else f"{self._base_url}{full_mcp_path}")
    self._jwt = JWTIssuer(issuer=self._base_url, audience=audience,
                          signing_key=self._signing_key)
```

### 5.4 `server.py` — 透传 root_path

```python
auth=MemlordOAuthProvider(
    base_url=settings.base_url,
    jwt_secret=settings.oauth_jwt_secret,
    session_factory=session,
    root_path=settings.root_path,
),
```

### 5.5 `utils/inject_client_id.py` — 不需要改

mount 剥离前缀后内部路径仍是 `/token`。

### 5.6 `sso.py` — Azure SSO 回调路径

```python
rp = settings.root_path.rstrip("/")
return RedirectResponse(f"{rp}/ui/login?error=azure_failed", status_code=303)
return RedirectResponse(f"{rp}/", status_code=303)
```

Azure 回调地址拼接不变（仍用 `settings.base_url`）。

### 5.7 `ui/login.py` — 登录/注册/邮件

#### RedirectResponse 路径前缀（8 处）

```python
rp = settings.root_path.rstrip("/")
RedirectResponse(f"{rp}/ui/login", status_code=303)
RedirectResponse(f"{rp}/ui/login?reset=1", status_code=303)
RedirectResponse(f"{rp}/", status_code=303)
RedirectResponse(f"{rp}/?verification_sent=1", status_code=303)
```

#### `_safe_redirect` 函数（1 处）

```python
def _safe_redirect(next: str) -> str:
    rp = settings.root_path.rstrip("/")
    default = f"{rp}/" if rp else "/"
    return next if (next.startswith("/") and not next.startswith("//")) else default
```

#### `next` 参数默认值（4 处）

```python
rp = settings.root_path.rstrip("/")
_default_next = f"{rp}/" if rp else "/"

async def login_get(request: Request, next: str = "") -> HTMLResponse:
    if not next: next = _default_next
    ...
async def login_post(..., next: str = Form(default="")) -> Response:
    if not next: next = _default_next
    ...
# register_get / register_post 同理
```

> **注意：** 不能直接用函数返回值作 `Form(default=...)`（Python 默认值在定义时求值）。改用 `default=""` 然后函数体内判断。

#### 邮件 body 不变

仍用 `settings.base_url`。

### 5.8 `ui/utils.py` — 工具层

#### cookie path

```python
rp = settings.root_path.rstrip("/") or "/"
response.set_cookie("memlord_session", ..., path=f"{rp}/", ...)
```

#### auth guard redirect

```python
rp = settings.root_path.rstrip("/")
headers={"Location": f"{rp}/ui/login?next={request.url.path}"}
```

### 5.9 `api/workspaces.py` — invite URL

L276：
```python
base = str(request.base_url).rstrip("/")
return InviteResponse(invite_url=f"{base}/ui/workspaces/join/{token}", ...)
```

**问题：** 如果反向代理没正确设置 `X-Forwarded-Proto` 和 `X-Forwarded-Host`，`request.base_url` 返回 `http://localhost:8000` 而不是 `https://example.com/memlord`。而且 mount 剥离前缀后，`request.base_url` 的路径部分可能也不带前缀。

**解决方案：** 使用 `settings.base_url` 替代 `request.base_url`：

```python
base = settings.base_url.rstrip("/")
return InviteResponse(invite_url=f"{base}/ui/workspaces/join/{token}", ...)
```

`settings.base_url` 是配置的完整公开 URL（包含路径前缀），不受代理配置影响。

### 5.10 模板层 — 静态 HTML + 动态 JS 路径

#### 静态 HTML 替换规则

| 情况 | 替换方式 | 示例 |
|---|---|---|
| `href="/xxx"` | `href="{{ root_path }}/xxx"` | `href="{{ root_path }}/ui/workspaces"` |
| `href="/"` | `href="{{ root_path or '/' }}"` | 避免空值变 `href=""` |
| `action="/xxx"` | `action="{{ root_path }}/xxx"` | `action="{{ root_path }}/ui/login"` |
| `src="/favicon.svg"` | `src="{{ root_path }}/favicon.svg"` | 静态资源引用 |

#### 动态 JS 路径替换规则

在模板的 `<script>` 或 Alpine.js 组件中：

| JS 模式 | 替换方式 |
|---|---|
| `fetch('/api/...')` | `fetch(rootPath + '/api/...')` |
| `:href="'/xxx' + expr"` | `:href="rootPath + '/xxx' + expr"` |
| `window.location.href = '/xxx'` | `window.location.href = rootPath + '/xxx'` |
| `window.location.href = '/'` | `window.location.href = rootPath || '/'` |

注入 JS 变量（在 `base.html` 的 `<head>` 中）：

```html
<script>var rootPath = "{{ root_path }}";</script>
```

#### 模板改动清单（16 个模板，~61 处）

| 模板 | 静态路径 | 动态 JS | 典型路径 |
|---|---|---|---|
| `base.html` | 7 | 0 | `/`, `/ui/workspaces`, `/ui/settings`, `/search`, `/favicon.svg` |
| `login.html` | 4 | 0 | `/auth/azure/login`, `/ui/login`, `/ui/forgot-password`, `/ui/register` |
| `register.html` | 2 | 0 | `/ui/register`, `/ui/login` |
| `forgot_password.html` | 2 | 0 | `/ui/forgot-password`, `/ui/login` |
| `reset_password.html` | 2 | 0 | `/ui/reset-password`, `/ui/login` |
| `index.html` | 2 | 8 | `/?workspace=`, `/memory/...`, `/?tag=`, `fetch('/api/...')` |
| `memory.html` | 1 | 6 | `/`, `/?tag=`, `fetch('/api/memories/...')` |
| `search.html` | 0 | 3 | `/memory/...`, `/?tag=`, `fetch('/api/search')` |
| `workspaces.html` | 1 | 2 | `/ui/workspaces/new`, `fetch('/api/workspaces')` |
| `workspace_new.html` | 2 | 2 | `/ui/workspaces`, `fetch('/api/workspaces')` |
| `workspace_detail.html` | 1 | 9 | `/ui/workspaces`, `/`, `fetch('/api/workspaces/...')` |
| `workspace_join.html` | 2 | 2 | `/ui/workspaces`, `/`, `fetch('/api/workspaces/join/')` |
| `verify_email.html` | 3 | 0 | `/` |
| `settings.html` | 0 | 3 | `fetch('/ui/settings/api-keys')` |

---

## 6. MCP Client 侧配置变更

```json
{
  "mcpServers": {
    "memlord": {
      "url": "https://example.com/memlord/mcp"
    }
  }
}
```

---

## 7. 反向代理配置示例

### Nginx

```nginx
location /memlord/ {
    proxy_pass http://127.0.0.1:8000/memlord/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /memlord;
}
```

> **重要 1：** 必须设置 `X-Forwarded-Proto` 和 `X-Forwarded-Host`，否则 `request.base_url` 返回错误地址。
>
> **重要 2：** `proxy_pass` 末尾**必须带 `/`**。漏掉 `/` 会导致双重前缀（`/memlord/memlord/...`），404。

### `.env` 配置示例

```env
MEMLORD_BASE_URL=https://example.com/memlord
MEMLORD_ROOT_PATH=/memlord
MEMLORD_OAUTH_JWT_SECRET=***
```

---

## 8. 数据流 — 完整 OAuth + SSO 流程（subpath 下）

### 8.1 MCP Client OAuth 流程

```
MCP Client                              Memlord (subpath: /memlord)
    |                                         |
    |-- (1) GET /memlord/.well-known/ -------->|
    |     oauth-authorization-server           |
    |<-- (2) 返回发现文档，issuer =           |
    |     https://example.com/memlord          |
    |                                         |
    |-- (3) GET /memlord/authorize? ... ------>|
    |<-- (4) 302 → /memlord/login?id=xxx      |
    |                                         |
    |-- (5) 用户在登录页输入邮箱密码 --------->|
    |<-- (6) 302 → /memlord/authorize?code=xxx|
    |                                         |
    |-- (7) POST /memlord/token -------------->|
    |     (mount 剥离前缀后，内部匹配 /token ✅) |
    |<-- (8) access_token + refresh_token      |
    |     (JWT aud = https://example.com/memlord) |
    |                                         |
    |-- (9) 后续请求带 token ----------------->|
    |     GET /memlord/mcp                     |
```

### 8.2 Azure SSO + Web UI 流程

```
浏览器                               Memlord                          Azure AD
  |                                    |                               |
  |-- (1) 访问 https://example.com/memlord -->                           |
  |<-- (2) 返回登录页，Azure 按钮 href -->                                |
  |     = /memlord/auth/azure/login     |                               |
  |                                    |                               |
  |-- (3) 点击 Azure 按钮 ----------->|                               |
  |                                    |-- (4) 302 → Azure 登录页 ------>|
  |                                    |     redirect_uri =             |
  |                                    |     https://example.com/memlord |
  |                                    |     /auth/azure/callback       |
  |<-- (5) 用户在 Azure 完成 SSO -------------------------------------->|
  |                                    |                               |
  |-- (6) Azure 回调 /memlord/auth/ -->|                               |
  |     azure/callback?code=xxx        |                               |
  |                                    |-- (7) 交换 token + 验证 id_token |
  |                                    |-- (8) 查找/创建用户             |
  |                                    |-- (9) 设置 cookie              |
  |                                    |     path=/memlord/             |
  |<-- (10) 302 → /memlord/ ----------|                               |
```

---

## 9. 测试验证清单

### 9.1 根路径部署（回归测试）

- [ ] `MEMLORD_ROOT_PATH=""` 时行为不变
- [ ] OAuth well-known 端点在 `/` 下可达
- [ ] MCP Client 可以正常完成 OAuth 流程
- [ ] Web UI 登录/注册正常
- [ ] Azure SSO 登录正常
- [ ] 邮件验证/重置密码链接正常
- [ ] Cookie 设置在 `/` path
- [ ] `/health` 和 `/favicon` 在根路径下可达
- [ ] 邀请链接 URL 格式正确

### 9.2 子路径部署

- [ ] `MEMLORD_ROOT_PATH=/memlord` 启动成功
- [ ] 访问 `https://example.com/memlord/` 返回 Web UI
- [ ] `GET /memlord/.well-known/oauth-authorization-server` 返回正确发现文档
- [ ] `issuer` 字段 = `https://example.com/memlord`
- [ ] MCP Client 可以完成 OAuth 流程
- [ ] `POST /memlord/token` 正常处理
- [ ] JWT `aud` 字段 = `https://example.com/memlord`
- [ ] Web UI 登录页的 Azure SSO 按钮链接正确
- [ ] Azure SSO 回调正确跳转到 `/memlord/`
- [ ] 所有模板静态链接正确（导航栏、表单 action）
- [ ] 所有模板动态 JS 路径正确（fetch、Alpine :href、window.location）
- [ ] `<img src="/favicon.svg">` 在 subpath 下正确加载
- [ ] Cookie path = `/memlord/`
- [ ] 邮件验证链接包含 `/memlord` 前缀
- [ ] `GET /memlord/health` 返回正常
- [ ] `GET /memlord/favicon.svg` 返回正常
- [ ] 首页 logo 链接正确（非 `href=""`）
- [ ] 登录后 `next` 默认值正确（不是 `/` 而是 `/memlord/`）
- [ ] 邀请链接 URL 包含 `/memlord` 前缀（`https://example.com/memlord/ui/workspaces/join/...`）

---

## 10. 风险与注意事项

| 风险 | 缓解措施 |
|---|---|
| 反向代理未设置 `X-Forwarded-Proto/Host` | `request.base_url` 返回错误地址，文档中强调配置要求 |
| `base_url` 和 `root_path` 不一致 | 在启动时加校验：`base_url` 应以 `root_path` 结尾 |
| 旧版 MCP Client 缓存了旧的 well-known URL | well-known 端点自动响应新路径 |
| 子路径部署后，`/health` 端点路径变了 | 运维更新健康检查配置为 `/memlord/health` |
| 模板动态 JS 路径遗漏 | v0.4 已全面扫描 16 个模板的静态和动态路径，~61 处改动 |
| 反向代理未设 `X-Forwarded-Prefix`，`request.url.path` 不带前缀 | auth guard 的 `next` 参数会错误，已在代码中用 `settings.root_path` 构造默认值 |
| `proxy_pass` 末尾漏掉 `/` 导致双重前缀 | 文档中加粗强调 |
| `api/workspaces.py` 的 `request.base_url` 受代理配置影响 | v0.4 已改为使用 `settings.base_url`（不受代理影响） |

---

## 11. 后续扩展

- 支持自动从 `X-Forwarded-Prefix` header 推断 `root_path`（可选）
- 支持动态 `root_path`（运行时从请求推断，无需配置）
- 子域名部署文档（`memlord.example.com`，推荐方案，无需改代码）
