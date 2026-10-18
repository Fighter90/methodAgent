"""Шифрование секретов, которые администратор вводит в интерфейсе (ключи LLM, SSO, SMTP).

Только стандартная библиотека: ключ выводится из SECRET_KEY (PBKDF2), шифр — поток HMAC-SHA256
в режиме счётчика со случайным nonce, целостность — HMAC-SHA256 поверх nonce и шифртекста.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from functools import lru_cache

from app.core.config import get_settings

_PREFIX = 'enc1:'


class SecretUnreadable(ValueError):
    """Секрет зашифрован другим SECRET_KEY или повреждён."""


@lru_cache
def _keys(secret: str) -> tuple[bytes, bytes]:
    master = hashlib.pbkdf2_hmac('sha256', secret.encode(), b'metodagent-settings', 200_000)
    return hmac.new(master, b'enc', hashlib.sha256).digest(), hmac.new(master, b'mac', hashlib.sha256).digest()


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hmac.new(key, nonce + counter.to_bytes(8, 'big'), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:n])


def encrypt(plain: str) -> str:
    k_enc, k_mac = _keys(get_settings().secret_key)
    nonce = secrets.token_bytes(16)
    data = plain.encode()
    ct = bytes(a ^ b for a, b in zip(data, _stream(k_enc, nonce, len(data)), strict=True))
    tag = hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()
    return _PREFIX + base64.urlsafe_b64encode(nonce + tag + ct).decode()


def decrypt(token: str) -> str:
    if not token.startswith(_PREFIX):
        raise SecretUnreadable('Неизвестный формат секрета')
    raw = base64.urlsafe_b64decode(token[len(_PREFIX):].encode())
    nonce, tag, ct = raw[:16], raw[16:48], raw[48:]
    k_enc, k_mac = _keys(get_settings().secret_key)
    if not hmac.compare_digest(tag, hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()):
        raise SecretUnreadable('Секрет зашифрован другим SECRET_KEY')
    return bytes(a ^ b for a, b in zip(ct, _stream(k_enc, nonce, len(ct)), strict=True)).decode()


def mask(value: str) -> str:
    """Секрет никогда не уходит в API целиком: только последние 4 символа."""
    if not value:
        return ''
    return '••••' + value[-4:] if len(value) > 8 else '••••'
