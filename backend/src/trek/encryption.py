from __future__ import annotations

import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.environ.get("TREK_LLM_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("TREK_LLM_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode())


def encrypt_api_key(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()
