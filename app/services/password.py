"""密码保护 — hash + PBKDF2 + HMAC-signed unlock cookie"""

import hashlib
import hmac
import json
import os
import time

from config import SESSION_SECRET, UNLOCK_TTL

UNLOCK_COOKIE_OPTS = {
    "max_age": UNLOCK_TTL,
    "httponly": True,
    "samesite": "lax",
    "secure": True,
}


def hash_password(password: str) -> str:
    """PBKDF2 哈希密码，返回 salt$hash 格式"""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return f"{salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """验证密码，使用 hmac.compare_digest 防时序攻击"""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return hmac.compare_digest(key.hex(), hash_hex)
    except Exception:
        return False


def make_unlock_cookie(shortcode: str) -> str:
    """创建 site_unlock token（HMAC 签名 JSON payload）"""
    payload = json.dumps(
        {
            "shortcode": shortcode,
            "exp": int(time.time()) + UNLOCK_TTL,
        }
    )
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_unlock_cookie(token: str, expected_shortcode: str) -> bool:
    """验证 site_unlock token"""
    try:
        payload, sig = token.rsplit(":", 1)
        expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        data = json.loads(payload)
        if data["exp"] < time.time():
            return False
        return hmac.compare_digest(data["shortcode"], expected_shortcode)
    except Exception:
        return False
