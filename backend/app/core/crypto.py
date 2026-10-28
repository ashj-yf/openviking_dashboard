"""user key 留存加密。

看板留存的 OpenViking 用户密钥对称加密后落库，供数据面代理使用。
Fernet 主密钥由 SECRET_KEY 经 SHA-256 确定性派生（生产环境请确保
SECRET_KEY 已更换为随机长串，轮换密钥需另行迁移密文）。
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        digest = hashlib.sha256(get_settings().secret_key.encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("无法解密租户密钥：主密钥可能已变更") from exc
