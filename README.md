# static.jaschen.life

极简静态 HTML 托管服务 — 一行命令发布，获得永久短链接。

```
staticcli publish index.html
# → https://static.jaschen.life/AbCdEf12
```

## 功能

- **REST API** — 程序化发布、列出、删除静态 HTML 页面
- **Web 管理面板** — 浏览器端管理站点，邮箱 + 验证码注册
- **CLI 工具** — 终端一行命令发布，支持文件、stdin、直接 HTML 字符串
- **8 字符短链接** — 密码学随机生成，永久有效
- **零外部服务依赖** — SQLite 存储，文件系统存放 HTML

## 快速开始

### 本地开发

```bash
git clone git@github.com:Jaschenn/static-site-service.git
cd static-site-service
cp .env.example .env

# 直接运行
cd app
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000

# 或 Docker Compose
docker compose up
```

### 安装 CLI

```bash
mkdir -p ~/.local/bin
curl -sSL https://static.jaschen.life/cli -o ~/.local/bin/staticcli
chmod +x ~/.local/bin/staticcli
export PATH="$HOME/.local/bin:$PATH"
```

### 发布第一个页面

```bash
# 1. 获取 API Key（访问 https://static.jaschen.life 注册）
# 2. 配置 CLI
staticcli set-key sk_xxx
staticcli set-email you@example.com

# 3. 发布
echo '<html><body><h1>Hello World</h1></body></html>' > hello.html
staticcli publish hello.html

# 4. 访问输出的 URL
```

## 架构

```
                 ┌──────────────┐
                 │   Nginx      │  443 SSL 终止 + 反向代理
                 └──────┬───────┘
                        │ :8090
                 ┌──────▼───────┐
                 │  Docker      │
                 │  ┌─────────┐ │
                 │  │ FastAPI  │ │  Python 3.11 + uvicorn
                 │  │ Jinja2   │ │
                 │  │ SQLite   │ │
                 │  └─────────┘ │
                 └──────┬───────┘
                        │
                 ┌──────▼───────┐
                 │   /data      │  SQLite DB + HTML 文件
                 └──────────────┘
```

### 目录结构

```
app/
├── main.py              # FastAPI 入口，路由注册
├── config.py            # 环境变量配置
├── database.py          # SQLite 初始化
├── models.py            # 数据类定义
├── security.py          # 安全头中间件
├── ratelimit.py         # API 速率限制
├── routes/
│   ├── api_keys.py      # API Key 管理（注册/验证）
│   ├── api_sites.py     # 站点管理（发布/列出/删除）
│   ├── web.py           # Web UI 路由
│   └── serve.py         # 短链接内容 Serve
├── services/
│   ├── email.py         # 验证码邮件
│   └── shortcode.py     # 短链接生成
├── templates/           # Jinja2 模板
└── static/              # CSS 等静态资源
cli/
└── staticcli.py         # 独立 CLI 工具
```

### 技术栈

| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI (Python 3.11+) |
| 数据库 | SQLite (aiosqlite) |
| 模板 | Jinja2 |
| 反向代理 | Nginx + Let's Encrypt |
| 容器 | Docker + Docker Compose |
| CI/CD | GitHub Actions |

## API 参考

所有 API 端点以 `/api` 为前缀。

### 获取 API Key

```http
POST /api/keys
Content-Type: application/json

{"email": "you@example.com"}
```

返回验证码已发送。然后：

```http
POST /api/keys/verify
Content-Type: application/json

{"email": "you@example.com", "token": "123456"}
```

返回 `{"api_key": "sk_xxx..."}`。

### 发布站点

```http
POST /api/sites
X-API-Key: sk_xxx
Content-Type: text/html

<!DOCTYPE html>...
```

返回 `{"shortcode": "AbCdEf12", "url": "https://static.jaschen.life/AbCdEf12"}`。

### 列出站点

```http
GET /api/sites
X-API-Key: sk_xxx
X-Email: you@example.com
```

### 删除站点

```http
DELETE /api/sites/{shortcode}
X-API-Key: sk_xxx
X-Email: you@example.com
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DOMAIN` | `http://localhost:8000` | 生成短链接用的域名 |
| `DATABASE_PATH` | `/data/data.db` | SQLite 路径 |
| `SITES_DIR` | `/data/sites` | HTML 文件存储目录 |
| `MAX_UPLOAD_SIZE` | `4194304` | 上传限制（字节） |
| `MOCK_EMAIL` | `true` | 跳过 SMTP，打印验证码到 stdout |
| `SMTP_HOST` | — | SMTP 服务器 |
| `SMTP_PORT` | `587` | SMTP 端口 |
| `SMTP_USER` | — | SMTP 用户名 |
| `SMTP_PASS` | — | SMTP 密码 |
| `SMTP_FROM` | `noreply@static.jaschen.life` | 发件人 |
| `TOKEN_EXPIRY` | `600` | 验证码有效期（秒） |
| `SESSION_SECRET` | `change-me-in-production` | Session HMAC 密钥 |

## 部署

### 首次部署

```bash
# 服务器上
git clone git@github.com:Jaschenn/static-site-service.git
cd static-site-service
cp .env.example .env
# 编辑 .env 填入生产环境配置
docker compose up -d
```

### CI/CD

推送代码到 `main` 分支后，GitHub Actions 自动：

1. **CI** — ruff 代码检查 + Docker 构建验证
2. **CD** — SSH 到服务器 → git pull → `docker compose up -d --build`

需要配置 GitHub Secrets：

| Secret | 说明 |
|---|---|
| `SSH_HOST` | 服务器 IP 或域名 |
| `SSH_USER` | SSH 用户名 |
| `SSH_PRIVATE_KEY` | SSH 私钥 |
| `REMOTE_DIR` | 服务器上仓库路径 |

### 更新

```bash
# 方式 1：推送代码触发自动部署
git push origin main

# 方式 2：服务器上手动更新
ssh your-server
cd /path/to/static-site-service
git pull origin main
docker compose up -d --build
```
