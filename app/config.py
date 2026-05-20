import os

# 域名（生成短链用）
DOMAIN = os.getenv("DOMAIN", "http://localhost:8000")

# 数据库路径
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/data.db")

# 站点文件存储路径
SITES_DIR = os.getenv("SITES_DIR", "/data/sites")

# 上传限制（字节）
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 4 * 1024 * 1024))

# 邮件配置
MOCK_EMAIL = os.getenv("MOCK_EMAIL", "true").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@static.jaschen.life")

# 验证码有效期（秒）
TOKEN_EXPIRY = int(os.getenv("TOKEN_EXPIRY", 600))

# Session 密钥（生产环境请务必修改）
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-in-production")

# 密码保护 unlock cookie 有效期（秒），默认 24 小时
UNLOCK_TTL = int(os.getenv("UNLOCK_TTL", 86400))
