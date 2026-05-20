# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

极简静态 HTML 托管服务，部署在 `static.jaschen.life`。用户通过 API Key 认证后发布 HTML 文件，获得 8 字符短链接（如 `https://static.jaschen.life/AbCdEf12`）供公开访问。提供 REST API、Web 管理面板和 CLI 工具。发布时可设置密码保护（PBKDF2 哈希 + HMAC-signed unlock cookie），访问者需在 `/unlock/{shortcode}` 页面输入密码。

## 常用命令

### 本地开发
```bash
# 直接运行（无 Docker）
cd app && pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8000

# Docker Compose（映射到 127.0.0.1:8090）
docker compose up
```

### 依赖
所有依赖在 `app/requirements.txt`（fastapi、uvicorn、jinja2、aiosqlite、python-multipart）。Lint 通过 `ruff`（不需要项目配置）。

### CI/CD
`.github/workflows/` 中有两个工作流：
- **CI**（push/PR）：ruff lint + format check + Python compileall + Docker 构建
- **CD**（push main）：SSH 部署 → git pull → Docker rebuild → 更新 nginx 配置并 reload

### CLI
```bash
# 安装 CLI 工具
curl -sSL https://static.jaschen.life/cli -o ~/.local/bin/staticcli

# 使用
python ~/.local/bin/staticcli set-key sk_xxx
python ~/.local/bin/staticcli publish page.html
python ~/.local/bin/staticcli publish secret.html --password mypassword  # 密码保护
python ~/.local/bin/staticcli list
```

**注意**：CLI 文件维护了两份副本——`cli/staticcli.py`（仓库根目录）和 `app/staticcli.py`（Docker 构建上下文内，由 `/cli` 端点提供）。修改 CLI 时**两个文件都必须更新**。

## 架构

### 技术栈
Python 3.11+, FastAPI, SQLite (aiosqlite), Jinja2 模板, Docker, Nginx 反向代理

### 关键架构决策

**路由注册顺序至关重要** — `main.py` 按顺序注册路由：API routes → Web routes → Serve catch-all。`serve.py` 中的 `GET /{shortcode}` 必须是最后一个，否则通配路由会吞掉其他路由的请求。

**双重认证模型**：
- **API 认证**（机器）：通过 `X-API-Key` header（发布操作）或 `X-Email` + `X-API-Key`（列出/删除操作）
- **Web Session**（浏览器）：无状态 HMAC-signed cookie（`SESSION_SECRET` 签名，1 小时有效期），逻辑在 `routes/web.py` 中的 `make_session()` / `verify_session()`

**文件存储**：发布的 HTML 直接存储在文件系统的 `SITES_DIR/{shortcode}.html`，数据库仅存元数据（shortcode、email、title、size_bytes）。

**数据模型未被实际使用**：`models.py` 定义了数据类（`User`、`Site`、`ApiKey` 等），但路由层直接使用原始 SQLite 行和字典。若新增功能，可从模型层开始统一。

### 目录结构

```
app/
├── main.py          # FastAPI 入口：lifespan（初始化 DB + 创建目录）、CORS、路由注册
├── config.py        # 所有环境变量（DOMAIN, DATABASE_PATH, SITES_DIR, SMTP_*, SESSION_SECRET 等）
├── database.py      # SQLite 初始化（users/verification_tokens/api_keys/sites 表），get_db() 连接工厂
├── models.py        # 数据类定义（目前未被路由实际使用）
├── routes/          # 路由层
│   ├── api_keys.py  # POST /api/keys（发送验证码）, POST /api/keys/verify（兑换 API Key）
│   ├── api_sites.py # POST /api/sites（发布，支持 X-Site-Password）, GET /api/sites（列表）, DELETE /api/sites/{code}（删除）
│   ├── serve.py     # GET /{shortcode}（提供 HTML，有密码则先检查 unlock cookie）, GET /404
│   └── web.py       # Web UI：首页、/verify、/login、/dashboard、/logout、/delete/{code}、/unlock/{code}、/cli
├── security.py      # SecurityHeadersMiddleware（X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy）
├── ratelimit.py     # 内存速率限制器（IP 级 + key 级），用于 API 端点和 unlock 提交
├── services/
│   ├── email.py     # 验证码生成 + SMTP 发送（MOCK_EMAIL=true 时打印到 stdout）
│   ├── shortcode.py # 8 字符密码学随机短码生成
│   └── password.py  # PBKDF2 密码哈希 + HMAC-signed unlock cookie（make/verify）
├── templates/       # Jinja2 模板（base.html, index.html, login.html, verify.html, dashboard.html, unlock.html）
├── static/          # 静态资源（style.css）
└── staticcli.py     # CLI 工具副本（/cli 端点提供此文件）
cli/
└── staticcli.py     # 独立 CLI 工具（零外部依赖，通过 urllib.request 调用 API）
nginx/               # Nginx 配置（docker-compose 内部 + 生产环境）
.github/workflows/   # CI/CD（ci.yml + cd.yml）
```

### 数据库设计
- **users**: `email TEXT PK`, `verified INTEGER`, `created_at`
- **verification_tokens**: `id PK`, `email FK`, `token`, `expires_at`, `used`
- **api_keys**: `key TEXT PK`（`sk_` + 32 hex）, `email FK`, `name`, `created_at`
- **sites**: `shortcode TEXT PK`（8 char alphanumeric）, `email FK`, `title`, `size_bytes`, `password_hash TEXT`（可为 NULL，PBKDF2 格式 `salt$hash`）, `created_at`

### 配置（通过 .env）
关键默认值：`DATABASE_PATH=/data/data.db`, `SITES_DIR=/data/sites`, `MAX_UPLOAD_SIZE=4MB`, `MOCK_EMAIL=true`, `TOKEN_EXPIRY=600`（10 分钟）, `SESSION_SECRET=change-me-in-production`, `UNLOCK_TTL=86400`（24 小时）

### CSRF 防护

Session cookie 中包含 `csrf` 字段。所有 Web UI 的 POST 表单都需要提交 `csrf_token` 隐藏域，服务端通过 `_require_csrf()` 验证 session 中的值。无 session 的用户（首次访问）CSRF 校验自动放行——验证码/API Key 作为独立防线。Session cookie 已设置 `secure=True`（仅 HTTPS）、`httponly=True`、`samesite=lax`。

### 密码保护

发布时可通过 `X-Site-Password` header（API）或 `--password` flag（CLI）设置密码：
- **密码存储**：PBKDF2-SHA256（100,000 次迭代，32 字节 salt），格式 `salt$hash`
- **比对**：`hmac.compare_digest` 防时序攻击
- **Unlock cookie**：HMAC 签名 JSON（含 shortcode + exp），24 小时 TTL，绑定特定短码
- **流程**：`serve.py` 检测到密码则重定向到 `/unlock/{shortcode}` → 用户输入密码 → 正确则设 cookie 并跳回
- **为何 `/unlock` 在 web.py**：serve.py 对用户页面设置了 `form-action 'none'` CSP，无法提交表单

### 安全头

`SecurityHeadersMiddleware` 全局注入 `X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: strict-origin-when-cross-origin`。用户页面（`serve.py`）额外返回严格的 `Content-Security-Policy` 头（含 `form-action 'none'`），禁止脚本和框架嵌入。

### 验证码/API Key 逻辑在 routes 中存在重复
`api_keys.py` 和 `web.py` 中的验证码兑换流程相似但独立实现。如需修改这个流程，两处都需要更新。

### CLI 文件维护两份副本
`cli/staticcli.py` 和 `app/staticcli.py` 内容必须保持同步。`app/` 中的副本由 Docker 部署，通过 `/cli` 端点提供给用户下载。修改 CLI 时两处都需更新。

### RESERVED_PATHS
`serve.py` 的 `RESERVED_PATHS` 集合防止短码与 Web UI 路由冲突。包含：`login`、`dashboard`、`verify`、`logout`、`404`、`api`、`favicon.ico`、`robots.txt`、`static`、`delete`、`health`、`unlock`。新增 Web 路由时需同步更新此集合。

### 速率限制

`ratelimit.py` 提供内存级的 `RateLimiter` 类：
- `POST /api/keys`：每 IP 每分钟最多 3 次
- `POST /api/keys/verify`：每 IP 每分钟最多 10 次，每邮箱 10 分钟内最多 5 次
- `POST /unlock/{shortcode}`：每 IP 每分钟最多 5 次（公开表单，速率限制为主要防线）
- 429 状态码表示被限流
