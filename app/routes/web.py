"""Web UI 路由"""
import hashlib
import hmac
import json
import time
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_db
from config import SESSION_SECRET

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="templates")

# 简单 Session（基于 HMAC cookie，无状态）
SESSION_TTL = 3600  # 1 小时


def make_session(email: str) -> str:
    """创建 session token"""
    payload = json.dumps({"email": email, "exp": int(time.time()) + SESSION_TTL})
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_session(token: str) -> str | None:
    """验证 session token，返回 email 或 None"""
    try:
        payload, sig = token.rsplit(":", 1)
        expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload)
        if data["exp"] < time.time():
            return None
        return data["email"]
    except Exception:
        return None


def get_session_email(request: Request) -> str | None:
    """从 cookie 获取当前用户 email"""
    token = request.cookies.get("session")
    if not token:
        return None
    return verify_session(token)


# ─── 页面路由 ───


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页"""
    return templates.TemplateResponse(request, "index.html")


@router.post("/", response_class=HTMLResponse)
async def index_submit(request: Request, email: str = Form(...)):
    """首页提交邮箱 → 发送验证码 → 跳转验证页"""
    import re
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return templates.TemplateResponse(request, "index.html", {"error": "邮箱格式不正确"})

    # 调用 API key 创建逻辑（直接内联，避免 HTTP 调用）
    from services.email import generate_token, token_expires_at, send_verification_email

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

    return RedirectResponse(f"/verify?email={email}", status_code=303)


@router.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, email: str = ""):
    """验证页"""
    return templates.TemplateResponse(request, "verify.html", {"email": email})


@router.post("/verify", response_class=HTMLResponse)
async def verify_submit(request: Request, email: str = Form(...), token: str = Form(...)):
    """验证提交 → 显示 API Key"""
    email = email.strip().lower()
    token = token.strip()

    # 调用验证逻辑
    import secrets as sec
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
            return templates.TemplateResponse(request, "verify.html", {
                "email": email,
                "error": "验证码无效或已过期"
            })

        await db.execute("UPDATE verification_tokens SET used = 1 WHERE id = ?", (row["id"],))
        await db.execute(
            "INSERT INTO users (email, verified) VALUES (?, 1) ON CONFLICT(email) DO UPDATE SET verified = 1",
            (email,),
        )
        api_key = "sk_" + sec.token_hex(16)
        await db.execute("INSERT INTO api_keys (key, email) VALUES (?, ?)", (api_key, email))
        await db.commit()
    finally:
        await db.close()

    # 生成 session 并设置 cookie
    resp = templates.TemplateResponse(request, "verify.html", {
        "email": email,
        "api_key": api_key,
        "success": True,
    })
    resp.set_cookie(
        key="session",
        value=make_session(email),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页"""
    email = get_session_email(request)
    if email:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html")


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...), key: str = Form(...)):
    """登录提交"""
    email = email.strip().lower()
    key = key.strip()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM api_keys WHERE key = ? AND email = ?",
            (key, email),
        )
        if not await cursor.fetchone():
            return templates.TemplateResponse(request, "login.html", {
                "error": "邮箱与 API Key 不匹配"
            })
    finally:
        await db.close()

    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie(
        key="session",
        value=make_session(email),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
    )
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
            "SELECT shortcode, title, size_bytes, created_at FROM sites WHERE email = ? ORDER BY created_at DESC",
            (email,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    sites = [{
        "shortcode": r["shortcode"],
        "title": r["title"] or "无标题",
        "url": f"https://static.jaschen.life/{r['shortcode']}",
        "size_bytes": r["size_bytes"],
        "created_at": r["created_at"],
    } for r in rows]

    return templates.TemplateResponse(request, "dashboard.html", {
        "email": email, "sites": sites,
    })


@router.post("/delete/{shortcode}")
async def delete_site_web(shortcode: str, request: Request):
    """Web 端删除站点"""
    email = get_session_email(request)
    if not email:
        return RedirectResponse("/login", status_code=303)

    import os, re
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


@router.get("/logout")
async def logout():
    """退出登录"""
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session")
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
