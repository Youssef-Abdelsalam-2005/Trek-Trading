from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trek.signer import (
    ALLOWED_PROGRAMS,
    _b58encode,
    _handle_request,
    _load_keypair,
    _validate_transaction,
)


def _make_keypair() -> tuple[bytes, bytes, bytes]:
    """Generate an Ed25519 keypair. Returns (secret_key_64, public_key_32, private_seed_32)."""
    private_key = Ed25519PrivateKey.generate()
    seed = private_key.private_bytes_raw()
    pub = private_key.public_key().public_bytes_raw()
    secret_key = seed + pub  # 64 bytes: Solana keypair format
    return secret_key, pub, seed


def _encrypt_keypair(secret_key: bytes) -> tuple[str, bytes]:
    """Encrypt a 64-byte keypair with Fernet. Returns (fernet_key_str, encrypted_blob)."""
    fernet_key = Fernet.generate_key()
    f = Fernet(fernet_key)
    return fernet_key.decode(), f.encrypt(secret_key)


def _write_compact_u16(val: int) -> bytes:
    parts = []
    while True:
        byte = val & 0x7F
        val >>= 7
        if val:
            parts.append(byte | 0x80)
        else:
            parts.append(byte)
            break
    return bytes(parts)


def _b58decode(s: str) -> bytes:
    alphabet = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = 0
    for c in s.encode():
        num = num * 58 + alphabet.index(c)
    pad_size = 0
    for c in s.encode():
        if c == alphabet[0]:
            pad_size += 1
        else:
            break
    result = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * pad_size + result


def _build_legacy_tx(
    signer_pubkey: bytes,
    program_ids: list[str],
    num_required_sigs: int = 1,
) -> bytes:
    """Build a minimal legacy transaction with the given program IDs."""
    account_keys = [signer_pubkey]
    for pid_str in program_ids:
        pid_bytes = _b58decode(pid_str)
        if len(pid_bytes) < 32:
            pid_bytes = b"\x00" * (32 - len(pid_bytes)) + pid_bytes
        account_keys.append(pid_bytes)

    # Instructions: one per program
    instructions = []
    for i, _ in enumerate(program_ids):
        program_id_index = i + 1  # signer is at index 0
        instructions.append((program_id_index, [], b""))

    # Build message
    header = bytes([num_required_sigs, 0, len(program_ids)])
    msg = header
    msg += _write_compact_u16(len(account_keys))
    for key in account_keys:
        msg += key
    msg += b"\x00" * 32  # recent blockhash

    msg += _write_compact_u16(len(instructions))
    for prog_idx, acct_idxs, data in instructions:
        msg += bytes([prog_idx])
        msg += _write_compact_u16(len(acct_idxs))
        msg += bytes(acct_idxs)
        msg += _write_compact_u16(len(data))
        msg += data

    # Build transaction: 1 signature (zeroed) + message
    tx = _write_compact_u16(1) + b"\x00" * 64 + msg
    return tx


class TestBase58:
    def test_encode_system_program(self):
        key = b"\x00" * 32
        assert _b58encode(key) == "1" * 32

    def test_roundtrip(self):
        secret_key, pub, _ = _make_keypair()
        encoded = _b58encode(pub)
        decoded = _b58decode(encoded)
        if len(decoded) < 32:
            decoded = b"\x00" * (32 - len(decoded)) + decoded
        assert decoded == pub


class TestLoadKeypair:
    def test_success(self, tmp_path: Path):
        secret_key, pub, _ = _make_keypair()
        fernet_key_str, encrypted = _encrypt_keypair(secret_key)

        key_file = tmp_path / "wallet.key.enc"
        key_file.write_bytes(encrypted)

        env = {
            "WALLET_ENCRYPTION_KEY": fernet_key_str,
            "WALLET_KEY_PATH": str(key_file),
        }
        with patch.dict(os.environ, env):
            loaded_secret, loaded_pub = _load_keypair()
            assert loaded_secret == secret_key
            assert loaded_pub == pub

    def test_missing_env_var(self, tmp_path: Path):
        env = {"WALLET_ENCRYPTION_KEY": "", "WALLET_KEY_PATH": str(tmp_path / "x")}
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(RuntimeError, match="WALLET_ENCRYPTION_KEY not set"):
                _load_keypair()

    def test_missing_file(self, tmp_path: Path):
        env = {
            "WALLET_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "WALLET_KEY_PATH": str(tmp_path / "nonexistent"),
        }
        with patch.dict(os.environ, env):
            with pytest.raises(RuntimeError, match="not found"):
                _load_keypair()

    def test_wrong_key(self, tmp_path: Path):
        secret_key, _, _ = _make_keypair()
        _, encrypted = _encrypt_keypair(secret_key)
        wrong_key = Fernet.generate_key().decode()

        key_file = tmp_path / "wallet.key.enc"
        key_file.write_bytes(encrypted)

        env = {
            "WALLET_ENCRYPTION_KEY": wrong_key,
            "WALLET_KEY_PATH": str(key_file),
        }
        with patch.dict(os.environ, env):
            with pytest.raises(RuntimeError, match="Failed to decrypt"):
                _load_keypair()


class TestValidateTransaction:
    def test_valid_single_program(self):
        _, pub, _ = _make_keypair()
        tx = _build_legacy_tx(pub, ["11111111111111111111111111111111"])
        _validate_transaction(tx, pub)

    def test_valid_multiple_programs(self):
        _, pub, _ = _make_keypair()
        tx = _build_legacy_tx(pub, [
            "11111111111111111111111111111111",
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        ])
        _validate_transaction(tx, pub)

    def test_rejects_unknown_program(self):
        _, pub, _ = _make_keypair()
        tx = _build_legacy_tx(pub, ["Vote111111111111111111111111111111111111111"])
        with pytest.raises(ValueError, match="not in whitelist"):
            _validate_transaction(tx, pub)

    def test_rejects_wrong_signer(self):
        _, pub1, _ = _make_keypair()
        _, pub2, _ = _make_keypair()
        tx = _build_legacy_tx(pub1, ["11111111111111111111111111111111"])
        with pytest.raises(ValueError, match="not a required signer"):
            _validate_transaction(tx, pub2)

    def test_rejects_truncated(self):
        with pytest.raises(ValueError):
            _validate_transaction(b"\x00", b"\x00" * 32)


class TestHandleRequest:
    @pytest.fixture()
    def keypair(self):
        secret_key, pub, _ = _make_keypair()
        return secret_key, pub

    @pytest.mark.asyncio
    async def test_sign_valid(self, keypair):
        secret_key, pub = keypair
        tx = _build_legacy_tx(pub, ["11111111111111111111111111111111"])
        req = {"method": "sign", "transaction": base64.b64encode(tx).decode()}
        resp = await _handle_request(req, secret_key, pub)
        assert "signature" in resp
        sig = base64.b64decode(resp["signature"])
        assert len(sig) == 64

    @pytest.mark.asyncio
    async def test_sign_rejected_program(self, keypair):
        secret_key, pub = keypair
        tx = _build_legacy_tx(pub, ["Vote111111111111111111111111111111111111111"])
        req = {"method": "sign", "transaction": base64.b64encode(tx).decode()}
        resp = await _handle_request(req, secret_key, pub)
        assert "error" in resp
        assert "rejected" in resp["error"].lower()

    @pytest.mark.asyncio
    async def test_unknown_method(self, keypair):
        secret_key, pub = keypair
        resp = await _handle_request({"method": "foo"}, secret_key, pub)
        assert "error" in resp

    @pytest.mark.asyncio
    async def test_missing_transaction(self, keypair):
        secret_key, pub = keypair
        resp = await _handle_request({"method": "sign"}, secret_key, pub)
        assert "error" in resp

    @pytest.mark.asyncio
    async def test_invalid_base64(self, keypair):
        secret_key, pub = keypair
        resp = await _handle_request(
            {"method": "sign", "transaction": "not-base64!!!"},
            secret_key, pub,
        )
        assert "error" in resp


class TestSignatureVerification:
    def test_signature_verifies(self):
        secret_key, pub, seed = _make_keypair()
        tx = _build_legacy_tx(pub, ["11111111111111111111111111111111"])

        from trek.signer import _extract_message_bytes, _sign_message
        msg = _extract_message_bytes(tx)
        sig = _sign_message(msg, secret_key)

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public_key = Ed25519PublicKey.from_public_bytes(pub)
        public_key.verify(sig, msg)  # raises if invalid


class TestSocketPermission:
    @pytest.mark.asyncio
    async def test_eacces_when_socket_mode_0600(self):
        """Verify that a socket with mode 0600 owned by another user is not
        connectable by the current process. Since we can't create a different
        OS user in CI, we set mode 0000 on the socket to prove EACCES."""
        import socket
        import stat

        secret_key, pub, _ = _make_keypair()

        with tempfile.TemporaryDirectory() as tmpdir:
            sock_path = os.path.join(tmpdir, "sign.sock")

            with patch.dict(os.environ, {"SIGNER_SOCKET_PATH": sock_path}):
                from trek.signer import main as signer_main

                server = await asyncio.start_unix_server(
                    lambda r, w: w.close(),
                    path=sock_path,
                )
                os.chmod(sock_path, 0o000)

                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    with pytest.raises(PermissionError):
                        sock.connect(sock_path)
                finally:
                    sock.close()
                    server.close()
                    await server.wait_closed()
