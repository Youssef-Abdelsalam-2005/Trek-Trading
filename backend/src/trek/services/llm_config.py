from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("TREK_LLM_ENCRYPTION_KEY", "")
        if not key:
            raise RuntimeError("TREK_LLM_ENCRYPTION_KEY not set")
        try:
            _fernet = Fernet(key.encode())
        except Exception as exc:
            raise RuntimeError("TREK_LLM_ENCRYPTION_KEY is not a valid Fernet key") from exc
    return _fernet


def encrypt_api_key(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt API key — wrong encryption key or corrupted data") from exc


def mask_api_key(plaintext: str) -> str:
    if len(plaintext) <= 8:
        return "****"
    return f"{plaintext[:4]}...{plaintext[-4:]}"


class LLMConfigService:
    def __init__(self, pool):
        self._pool = pool

    async def upsert(
        self,
        base_url: str,
        model_name: str,
        api_key: str,
        *,
        experiment_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        encrypted = encrypt_api_key(api_key)
        masked = mask_api_key(api_key)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO llm_config (id, experiment_id, base_url, model_name, api_key_encrypted, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $2, $3, $4, now(), now())
                ON CONFLICT ON CONSTRAINT llm_config_experiment_id_key
                DO UPDATE SET base_url = $2, model_name = $3, api_key_encrypted = $4, updated_at = now()
                RETURNING id, experiment_id, base_url, model_name, created_at, updated_at
                """,
                experiment_id, base_url, model_name, encrypted,
            )
        result = dict(row)
        result["api_key_masked"] = masked
        return result

    async def get(self, experiment_id: uuid.UUID | None = None) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            if experiment_id is None:
                row = await conn.fetchrow(
                    "SELECT id, experiment_id, base_url, model_name, api_key_encrypted, created_at, updated_at "
                    "FROM llm_config WHERE experiment_id IS NULL"
                )
            else:
                row = await conn.fetchrow(
                    "SELECT id, experiment_id, base_url, model_name, api_key_encrypted, created_at, updated_at "
                    "FROM llm_config WHERE experiment_id = $1",
                    experiment_id,
                )
        if row is None:
            return None
        result = dict(row)
        plaintext = decrypt_api_key(result.pop("api_key_encrypted"))
        result["api_key_masked"] = mask_api_key(plaintext)
        return result

    async def delete(self, experiment_id: uuid.UUID | None = None) -> bool:
        async with self._pool.acquire() as conn:
            if experiment_id is None:
                result = await conn.execute(
                    "DELETE FROM llm_config WHERE experiment_id IS NULL"
                )
            else:
                result = await conn.execute(
                    "DELETE FROM llm_config WHERE experiment_id = $1",
                    experiment_id,
                )
        return result != "DELETE 0"

    async def get_decrypted_api_key(self, experiment_id: uuid.UUID | None = None) -> str | None:
        async with self._pool.acquire() as conn:
            if experiment_id is None:
                row = await conn.fetchrow(
                    "SELECT api_key_encrypted FROM llm_config WHERE experiment_id IS NULL"
                )
            else:
                row = await conn.fetchrow(
                    "SELECT api_key_encrypted FROM llm_config "
                    "WHERE experiment_id = $1",
                    experiment_id,
                )
                if row is None:
                    row = await conn.fetchrow(
                        "SELECT api_key_encrypted FROM llm_config WHERE experiment_id IS NULL"
                    )
        if row is None:
            return None
        return decrypt_api_key(row["api_key_encrypted"])
