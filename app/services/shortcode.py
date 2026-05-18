import secrets
import string

ALPHABET = string.ascii_letters + string.digits
SHORTCODE_LENGTH = 8


def generate_shortcode(length: int = SHORTCODE_LENGTH) -> str:
    """生成随机短码（8 位字母数字）"""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
