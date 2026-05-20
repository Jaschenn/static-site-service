"""站点发布与管理路由"""
import os
import re

from fastapi import APIRouter, HTTPException, Request

from config import MAX_UPLOAD_SIZE, SITES_DIR
from database import get_db
from services.shortcode import generate_shortcode

router = APIRouter(prefix="/api/sites", tags=["sites"])


async def verify_api_key(key: str):
    """验证 API Key 是否有效，返回 email"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT email FROM api_keys WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="API Key 无效")
        return row["email"]
    finally:
        await db.close()


async def verify_email_key(email: str, key: str):
    """验证 Email + API Key 匹配"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT email FROM api_keys WHERE key = ? AND email = ?",
            (key, email),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="邮箱与 API Key 不匹配")
        return row["email"]
    finally:
        await db.close()


def extract_title(html: str) -> str:
    """从 HTML 提取标题"""
    match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()[:200]
    return ""


@router.post("")
async def publish_site(request: Request):
    """发布静态 HTML（Auth: X-API-Key）"""

    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        raise HTTPException(status_code=401, detail="缺少 X-API-Key")

    # 读取 body
    body = await request.body()
    if len(body) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"内容超过 {MAX_UPLOAD_SIZE // 1024 // 1024}MB 限制")

    try:
        html = body.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail="内容必须是有效的 UTF-8 文本") from e

    # 验证简单 HTML（至少包含 <html 或常见标签）
    if not re.search(r"<(!DOCTYPE|html|body|head|div|p|h[1-6]|span|a)\b", html, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="内容看起来不是有效的 HTML")

    email = await verify_api_key(api_key)

    # 确保目录存在
    os.makedirs(SITES_DIR, exist_ok=True)

    # 生成唯一短码
    shortcode = None
    db = await get_db()
    try:
        for _ in range(10):  # 最多重试 10 次
            code = generate_shortcode()
            cursor = await db.execute("SELECT 1 FROM sites WHERE shortcode = ?", (code,))
            if not await cursor.fetchone():
                shortcode = code
                break

        if not shortcode:
            raise HTTPException(status_code=500, detail="短码生成失败，请重试")

        # 写文件
        filepath = os.path.join(SITES_DIR, f"{shortcode}.html")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        title = extract_title(html)
        size = len(body)

        # 写数据库
        await db.execute(
            "INSERT INTO sites (shortcode, email, title, size_bytes) VALUES (?, ?, ?, ?)",
            (shortcode, email, title, size),
        )
        await db.commit()

        return {
            "shortcode": shortcode,
            "url": f"https://static.jaschen.life/{shortcode}",
            "title": title,
            "size_bytes": size,
        }

    finally:
        await db.close()


@router.get("")
async def list_sites(request: Request):
    """列出我的站点（Auth: X-Email + X-API-Key）"""

    email = request.headers.get("X-Email", "")
    api_key = request.headers.get("X-API-Key", "")

    if not email or not api_key:
        raise HTTPException(status_code=401, detail="需要 X-Email 和 X-API-Key")

    await verify_email_key(email, api_key)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT shortcode, title, size_bytes, created_at FROM sites WHERE email = ? ORDER BY created_at DESC",
            (email,),
        )
        rows = await cursor.fetchall()

        sites = []
        for row in rows:
            sites.append({
                "shortcode": row["shortcode"],
                "url": f"https://static.jaschen.life/{row['shortcode']}",
                "title": row["title"],
                "size_bytes": row["size_bytes"],
                "created_at": row["created_at"],
            })

        return {"sites": sites, "total": len(sites)}
    finally:
        await db.close()


@router.delete("/{shortcode}")
async def delete_site(shortcode: str, request: Request):
    """删除站点（Auth: X-Email + X-API-Key）"""

    email = request.headers.get("X-Email", "")
    api_key = request.headers.get("X-API-Key", "")

    if not email or not api_key:
        raise HTTPException(status_code=401, detail="需要 X-Email 和 X-API-Key")

    await verify_email_key(email, api_key)

    # 验证 shortcode 格式（8 位字母数字）
    if not re.match(r"^[a-zA-Z0-9]{8}$", shortcode):
        raise HTTPException(status_code=400, detail="无效的短码")

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM sites WHERE shortcode = ? AND email = ?",
            (shortcode, email),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="站点不存在或无权删除")

        # 删文件
        filepath = os.path.join(SITES_DIR, f"{shortcode}.html")
        if os.path.exists(filepath):
            os.remove(filepath)

        # 删数据库记录
        await db.execute("DELETE FROM sites WHERE shortcode = ?", (shortcode,))
        await db.commit()

        return {"message": f"站点 {shortcode} 已删除"}
    finally:
        await db.close()
