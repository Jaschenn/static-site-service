import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from config import MOCK_EMAIL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, TOKEN_EXPIRY


def generate_token() -> str:
    """生成 6 位数字验证码"""
    return f"{secrets.randbelow(1000000):06d}"


def token_expires_at() -> str:
    """验证码过期时间 (ISO 8601)"""
    expires = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_EXPIRY)
    return expires.isoformat()


def send_verification_email(email: str, token: str):
    """发送验证邮件"""

    if MOCK_EMAIL:
        # 开发模式：打印到日志
        print(f"\n{'=' * 60}")
        print(f"[MOCK EMAIL] To: {email}")
        print(f"[MOCK EMAIL] 验证码: {token}")
        print(f"[MOCK EMAIL] 有效期: {TOKEN_EXPIRY // 60} 分钟")
        print(f"{'=' * 60}\n")
        return

    # 生产模式：SMTP 发送
    subject = "static.jaschen.life — 邮箱验证码"
    body = f"""你好，

你的验证码是：{token}

该验证码 {TOKEN_EXPIRY // 60} 分钟内有效。

static.jaschen.life
"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = email

    # 端口 465 用 SSL，其他端口用 STARTTLS
    if SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()

    with server:
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM, [email], msg.as_string())
