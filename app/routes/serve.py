"""静态页面 Serve 路由"""

import os
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import SITES_DIR
from database import get_db
from services.password import verify_unlock_cookie

router = APIRouter(tags=["serve"])

# 保留路径，避免与 Web UI 冲突
RESERVED_PATHS = {
    "login",
    "dashboard",
    "verify",
    "logout",
    "404",
    "api",
    "favicon.ico",
    "robots.txt",
    "static",
    "delete",
    "health",
    "unlock",
}


@router.get("/404")
async def not_found_page():
    """404 页面"""
    return HTMLResponse(
        content="""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>404 - 页面不存在</title>
<style>
body { font-family: -apple-system, sans-serif; display: flex; justify-content: center;
align-items: center; min-height: 100vh; margin: 0; background: #fafafa; }
.box { text-align: center; }
h1 { font-size: 4rem; margin: 0; color: #333; }
p { color: #666; }
a { color: #0070f3; text-decoration: none; }
</style>
</head>
<body>
<div class="box">
<h1>404</h1>
<p>这个页面不存在，或者已被删除。</p>
<p><a href="/">← 回到首页</a></p>
</div>
</body>
</html>""",
        status_code=404,
    )


@router.get("/{shortcode}", response_class=HTMLResponse)
async def serve_site(shortcode: str, request: Request):
    """Serve 发布的静态 HTML"""

    # 保留路径检查
    if shortcode in RESERVED_PATHS:
        raise HTTPException(status_code=404, detail="页面不存在")

    # 验证 shortcode 格式（8 位字母数字）
    if not re.match(r"^[a-zA-Z0-9]{8}$", shortcode):
        raise HTTPException(status_code=404, detail="页面不存在")

    filepath = os.path.join(SITES_DIR, f"{shortcode}.html")

    # 查文件是否存在
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="页面不存在")

    # 检查密码保护
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT password_hash FROM sites WHERE shortcode = ?",
            (shortcode,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()

    if row and row["password_hash"]:
        unlock_token = request.cookies.get("site_unlock", "")
        if not unlock_token or not verify_unlock_cookie(unlock_token, shortcode):
            return RedirectResponse(f"/unlock/{shortcode}", status_code=302)

    # 读文件
    with open(filepath, encoding="utf-8") as f:
        html = f.read()

    return HTMLResponse(
        content=html,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; "
                "style-src 'unsafe-inline' https:; "
                "img-src data: https:; "
                "script-src 'none'; "
                "frame-ancestors 'none'; "
                "base-uri 'none'; "
                "form-action 'none'"
            ),
        },
    )
