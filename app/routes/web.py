"""Web UI 路由"""

import hashlib
import hmac
import json
import secrets
import time

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import SESSION_SECRET
from database import get_db
from services.password import UNLOCK_COOKIE_OPTS, make_unlock_cookie, verify_password

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="templates")

# 简单 Session（基于 HMAC cookie，无状态）
SESSION_TTL = 3600  # 1 小时


def make_session(email: str) -> str:
    """创建 session token（含 CSRF token）"""
    csrf = secrets.token_hex(32)
    payload = json.dumps(
        {
            "email": email,
            "exp": int(time.time()) + SESSION_TTL,
            "csrf": csrf,
        }
    )
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_session(token: str) -> dict | None:
    """验证 session token，返回 payload 或 None"""
    try:
        payload, sig = token.rsplit(":", 1)
        expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload)
        if data["exp"] < time.time():
            return None
        return data
    except Exception:
        return None


def get_session(request: Request) -> dict | None:
    """从 cookie 获取 session payload"""
    token = request.cookies.get("session")
    if not token:
        return None
    return verify_session(token)


def get_session_email(request: Request) -> str | None:
    """从 cookie 获取当前用户 email"""
    data = get_session(request)
    return data["email"] if data else None


def get_csrf_token(request: Request) -> str:
    """从 session 获取 CSRF token，无 session 时返回空字符串"""
    data = get_session(request)
    return data["csrf"] if data else ""


COOKIE_OPTS = {
    "max_age": SESSION_TTL,
    "httponly": True,
    "samesite": "lax",
    "secure": True,
}


def _set_session_cookie(resp, email: str):
    resp.set_cookie(key="session", value=make_session(email), **COOKIE_OPTS)


def _require_csrf(request: Request, form_data: dict):
    """验证 CSRF token，不通过则抛 403。
    注意：如果还没有 session，允许通过（验证码是独立防线）。"""
    session = get_session(request)
    if not session:
        return  # 无 session 时不强制 CSRF（验证码 / API Key 校验是独立防线）
    expected = session.get("csrf", "")
    submitted = form_data.get("csrf_token", "")
    if not hmac.compare_digest(submitted, expected):
        raise HTTPException(status_code=403, detail="CSRF 验证失败")


# ─── 页面路由 ───


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页"""
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/", response_class=HTMLResponse)
async def index_submit(request: Request, email: str = Form(...), csrf_token: str = Form("")):
    """首页提交邮箱 → 发送验证码 → 跳转验证页"""
    import re

    session = get_session(request)
    if session and not hmac.compare_digest(csrf_token, session.get("csrf", "")):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "error": "CSRF 验证失败",
                "csrf_token": session.get("csrf", ""),
            },
        )

    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "error": "邮箱格式不正确",
                "csrf_token": get_csrf_token(request),
            },
        )

    # 调用 API key 创建逻辑（直接内联，避免 HTTP 调用）
    from services.email import generate_token, send_verification_email, token_expires_at

    token = generate_token()
    expires_at = token_expires_at()

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO verification_tokens (email, token, expires_at) VALUES (?, ?, ?)",
            (email, token, expires_at),
        )
        await db.commit()
    finally:
        await db.close()

    send_verification_email(email, token)

    resp = RedirectResponse(f"/verify?email={email}", status_code=303)
    _set_session_cookie(resp, email)  # 提前设 session，使 verify 页的 CSRF 校验生效
    return resp


@router.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, email: str = ""):
    """验证页"""
    return templates.TemplateResponse(
        request,
        "verify.html",
        {
            "email": email,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/verify", response_class=HTMLResponse)
async def verify_submit(
    request: Request,
    email: str = Form(...),
    token: str = Form(...),
    csrf_token: str = Form(""),
):
    """验证提交 → 显示 API Key"""
    try:
        _require_csrf(request, {"csrf_token": csrf_token})
    except HTTPException:
        return templates.TemplateResponse(
            request,
            "verify.html",
            {
                "email": email,
                "error": "CSRF 验证失败，请刷新页面重试",
                "csrf_token": get_csrf_token(request),
            },
        )

    email = email.strip().lower()
    token = token.strip()

    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM verification_tokens
               WHERE email = ? AND token = ? AND used = 0
               AND expires_at > datetime('now')
               ORDER BY id DESC LIMIT 1""",
            (email, token),
        )
        row = await cursor.fetchone()
        if not row:
            return templates.TemplateResponse(
                request,
                "verify.html",
                {
                    "email": email,
                    "error": "验证码无效或已过期",
                    "csrf_token": get_csrf_token(request),
                },
            )

        await db.execute("UPDATE verification_tokens SET used = 1 WHERE id = ?", (row["id"],))
        await db.execute(
            "INSERT INTO users (email, verified) VALUES (?, 1) ON CONFLICT(email) DO UPDATE SET verified = 1",
            (email,),
        )
        api_key = "sk_" + secrets.token_hex(16)
        await db.execute("INSERT INTO api_keys (key, email) VALUES (?, ?)", (api_key, email))
        await db.commit()
    finally:
        await db.close()

    # 生成 session 并设置 cookie
    resp = templates.TemplateResponse(
        request,
        "verify.html",
        {
            "email": email,
            "api_key": api_key,
            "success": True,
            "csrf_token": get_csrf_token(request),
        },
    )
    _set_session_cookie(resp, email)
    return resp


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页"""
    email = get_session_email(request)
    if email:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    key: str = Form(...),
    csrf_token: str = Form(""),
):
    """登录提交"""
    session = get_session(request)
    if session and not hmac.compare_digest(csrf_token, session.get("csrf", "")):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "CSRF 验证失败",
                "csrf_token": session.get("csrf", ""),
            },
        )

    email = email.strip().lower()
    key = key.strip()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM api_keys WHERE key = ? AND email = ?",
            (key, email),
        )
        if not await cursor.fetchone():
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "邮箱与 API Key 不匹配",
                    "csrf_token": get_csrf_token(request),
                },
            )
    finally:
        await db.close()

    resp = RedirectResponse("/dashboard", status_code=303)
    _set_session_cookie(resp, email)
    return resp


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """管理面板"""
    email = get_session_email(request)
    if not email:
        return RedirectResponse("/login", status_code=303)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT shortcode, title, size_bytes, created_at, password_hash "
            "FROM sites WHERE email = ? ORDER BY created_at DESC",
            (email,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    sites = [
        {
            "shortcode": r["shortcode"],
            "title": r["title"] or "无标题",
            "url": f"https://static.jaschen.life/{r['shortcode']}",
            "size_bytes": r["size_bytes"],
            "created_at": r["created_at"],
            "has_password": bool(r["password_hash"]),
        }
        for r in rows
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "email": email,
            "sites": sites,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/delete/{shortcode}")
async def delete_site_web(shortcode: str, request: Request):
    """Web 端删除站点"""
    email = get_session_email(request)
    if not email:
        return RedirectResponse("/login", status_code=303)

    form_data = await request.form()
    try:
        _require_csrf(request, dict(form_data))
    except HTTPException:
        return RedirectResponse("/dashboard?error=csrf", status_code=303)

    import os
    import re

    from config import SITES_DIR

    if not re.match(r"^[a-zA-Z0-9]{8}$", shortcode):
        return RedirectResponse("/dashboard", status_code=303)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM sites WHERE shortcode = ? AND email = ?",
            (shortcode, email),
        )
        if await cursor.fetchone():
            await db.execute("DELETE FROM sites WHERE shortcode = ?", (shortcode,))
            await db.commit()
            filepath = os.path.join(SITES_DIR, f"{shortcode}.html")
            if os.path.exists(filepath):
                os.remove(filepath)
    finally:
        await db.close()

    return RedirectResponse("/dashboard", status_code=303)


@router.get("/unlock/{shortcode}", response_class=HTMLResponse)
async def unlock_page(request: Request, shortcode: str):
    """密码解锁页"""
    import re

    if not re.match(r"^[a-zA-Z0-9]{8}$", shortcode):
        raise HTTPException(status_code=404, detail="页面不存在")

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT password_hash FROM sites WHERE shortcode = ?",
            (shortcode,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()

    if not row or not row["password_hash"]:
        # 无密码保护 → 直接跳转到页面
        return RedirectResponse(f"/{shortcode}", status_code=302)

    return templates.TemplateResponse(
        request,
        "unlock.html",
        {
            "shortcode": shortcode,
        },
    )


@router.post("/unlock/{shortcode}")
async def unlock_submit(request: Request, shortcode: str):
    """解锁提交"""
    import re

    from ratelimit import RateLimiter

    if not re.match(r"^[a-zA-Z0-9]{8}$", shortcode):
        raise HTTPException(status_code=404, detail="页面不存在")

    # 速率限制：每 IP 每分钟 5 次
    unlock_limiter = RateLimiter(max_requests=5, window_seconds=60)
    try:
        await unlock_limiter(request)
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "unlock.html",
            {
                "shortcode": shortcode,
                "error": str(e.detail) if hasattr(e, "detail") else "请求太频繁，请稍后再试",
            },
        )

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT password_hash FROM sites WHERE shortcode = ?",
            (shortcode,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()

    if not row or not row["password_hash"]:
        return RedirectResponse(f"/{shortcode}", status_code=302)

    form_data = await request.form()
    password = form_data.get("password", "")

    if not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(
            request,
            "unlock.html",
            {
                "shortcode": shortcode,
                "error": "密码错误",
            },
            status_code=401,
        )

    # 密码正确 → 设 cookie 并跳转
    resp = RedirectResponse(f"/{shortcode}", status_code=303)
    resp.set_cookie(
        key="site_unlock",
        value=make_unlock_cookie(shortcode),
        **UNLOCK_COOKIE_OPTS,
    )
    return resp


@router.get("/logout")
async def logout():
    """退出登录"""
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session", secure=True)
    return resp


@router.get("/cli", response_class=HTMLResponse)
async def cli_download():
    """CLI 工具下载"""
    import os

    # Docker: /app/staticcli.py  |  本地: app/staticcli.py
    for path in ["staticcli.py", os.path.join(os.path.dirname(__file__), "..", "staticcli.py")]:
        if os.path.exists(path):
            with open(path) as f:
                content = f.read()
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse(content, media_type="text/x-python")
    return HTMLResponse(content="<h1>CLI 暂不可用</h1>", status_code=404)
