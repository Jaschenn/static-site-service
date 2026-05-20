"""API Key 管理路由"""

import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from database import get_db
from ratelimit import RateLimiter
from services.email import generate_token, send_verification_email, token_expires_at

router = APIRouter(prefix="/api/keys", tags=["keys"])

# 速率限制
send_limiter = RateLimiter(max_requests=3, window_seconds=60)  # 每 IP 每分钟 3 次发邮件
verify_limiter = RateLimiter(max_requests=10, window_seconds=60)  # 每 IP 每分钟 10 次验证
verify_email_limiter = RateLimiter(max_requests=5, window_seconds=600)  # 每邮箱 10 分钟 5 次


class CreateKeyRequest(BaseModel):
    email: str


class VerifyKeyRequest(BaseModel):
    email: str
    token: str


def generate_api_key() -> str:
    """生成 API Key: sk_ + 32 位 hex"""
    return "sk_" + secrets.token_hex(16)


@router.post("")
async def create_key(req: CreateKeyRequest, request: Request):
    """提交邮箱，发送验证码"""
    await send_limiter(request)

    email = req.email.strip().lower()

    # 基本邮箱格式校验
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

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

    return {"message": "验证码已发送到邮箱，请查收", "email": email}


@router.post("/verify")
async def verify_key(req: VerifyKeyRequest, request: Request):
    """验证邮箱，返回 API Key"""
    await verify_limiter(request)
    verify_email_limiter.check_key(req.email.strip().lower())

    email = req.email.strip().lower()
    token = req.token.strip()

    db = await get_db()
    try:
        # 查找有效验证码
        cursor = await db.execute(
            """SELECT * FROM verification_tokens
               WHERE email = ? AND token = ? AND used = 0
               AND expires_at > datetime('now')
               ORDER BY id DESC LIMIT 1""",
            (email, token),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="验证码无效或已过期")

        # 标记验证码已使用
        await db.execute(
            "UPDATE verification_tokens SET used = 1 WHERE id = ?",
            (row["id"],),
        )

        # 创建或更新用户
        await db.execute(
            "INSERT INTO users (email, verified) VALUES (?, 1) ON CONFLICT(email) DO UPDATE SET verified = 1",
            (email,),
        )

        # 生成 API Key
        api_key = generate_api_key()
        await db.execute(
            "INSERT INTO api_keys (key, email) VALUES (?, ?)",
            (api_key, email),
        )

        await db.commit()

        return {
            "api_key": api_key,
            "email": email,
            "message": "API Key 已生成，请妥善保存",
        }

    finally:
        await db.close()
