"""Cross-process Fernet integration test for LLM config.

Stores an API key via the LLMConfigService, then spawns a child process
that decrypts it using the same Fernet key and makes a test call to a
local mock OpenAI server.
"""
from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import sys
import tempfile
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

import asyncpg
import pytest
from cryptography.fernet import Fernet


DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://trek:trek_dev@localhost:5433/trek_step02_test",
)


class MockOpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        request = json.loads(body)

        auth = self.headers.get("Authorization", "")

        response = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{"message": {"content": "Hello from mock"}, "index": 0}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "_auth_received": auth,
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        resp_bytes = json.dumps(response).encode()
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    def log_message(self, format, *args):
        pass


def _child_decrypt_and_call(db_url: str, fernet_key: str, mock_port: int, result_file: str):
    """Child process: decrypt the API key from DB and call mock OpenAI."""
    import asyncio
    import asyncpg
    import json
    import urllib.request

    os.environ["TREK_LLM_ENCRYPTION_KEY"] = fernet_key
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from trek.services.llm_config import decrypt_api_key

    async def run():
        conn = await asyncpg.connect(db_url)
        row = await conn.fetchrow(
            "SELECT api_key_encrypted FROM llm_config WHERE experiment_id IS NULL"
        )
        await conn.close()

        if row is None:
            return {"error": "No config found"}

        api_key = decrypt_api_key(row["api_key_encrypted"])

        req = urllib.request.Request(
            f"http://127.0.0.1:{mock_port}/v1/chat/completions",
            data=json.dumps({"model": "test", "messages": [{"role": "user", "content": "hi"}]}).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read())
        return {
            "decrypted_key": api_key,
            "mock_response_ok": "choices" in body,
            "auth_received": body.get("_auth_received", ""),
        }

    result = asyncio.run(run())
    with open(result_file, "w") as f:
        json.dump(result, f)


@pytest.fixture
def fernet_key():
    return Fernet.generate_key().decode()


@pytest.fixture
def mock_openai_server():
    server = HTTPServer(("127.0.0.1", 0), MockOpenAIHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


@pytest.mark.asyncio
async def test_cross_process_fernet_roundtrip(fernet_key, mock_openai_server):
    """Store API key via service, decrypt in child process, call mock OpenAI."""
    os.environ["TREK_LLM_ENCRYPTION_KEY"] = fernet_key

    from trek.services.llm_config import LLMConfigService, _fernet
    import trek.services.llm_config as llm_mod
    llm_mod._fernet = None

    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=2)
    try:
        svc = LLMConfigService(pool)

        test_api_key = "sk-test-secret-key-12345678"
        await svc.upsert(
            base_url=f"http://127.0.0.1:{mock_openai_server}/v1",
            model_name="gpt-4",
            api_key=test_api_key,
        )

        config = await svc.get()
        assert config is not None
        assert config["api_key_masked"] == "sk-t...5678"
        assert "api_key_encrypted" not in config

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT api_key_encrypted FROM llm_config WHERE experiment_id IS NULL"
            )
        assert row is not None
        assert test_api_key not in row["api_key_encrypted"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            result_file = f.name

        proc = multiprocessing.Process(
            target=_child_decrypt_and_call,
            args=(DB_URL, fernet_key, mock_openai_server, result_file),
        )
        proc.start()
        proc.join(timeout=10)
        assert proc.exitcode == 0, f"Child process failed with exit code {proc.exitcode}"

        with open(result_file) as f:
            result = json.load(f)

        assert result["decrypted_key"] == test_api_key
        assert result["mock_response_ok"] is True
        assert result["auth_received"] == f"Bearer {test_api_key}"

        await svc.delete()
    finally:
        os.unlink(result_file)
        await pool.close()
        llm_mod._fernet = None
        os.environ.pop("TREK_LLM_ENCRYPTION_KEY", None)
