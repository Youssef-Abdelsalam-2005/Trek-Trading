from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import signal
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [signer] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

SOCKET_PATH = os.environ.get(
    "SIGNER_SOCKET_PATH", "/run/trek-signer/sign.sock",
)
_DEFAULT_WALLET_KEY_PATH = "/etc/trek-signer/wallet.key.enc"

ALLOWED_PROGRAMS: set[str] = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter v6
    "11111111111111111111111111111111",                  # System Program
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",     # SPL Token
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",    # Associated Token Account
    "T1pyyaTNZsKv2WcRAB8oVnk93mLJw2XzjtVYqCsaHqt",    # Jito Tip
}

# -- Base58 alphabet used by Solana for public keys --
_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> str:
    num = int.from_bytes(data, "big")
    result: list[int] = []
    while num > 0:
        num, rem = divmod(num, 58)
        result.append(_B58_ALPHABET[rem])
    for byte in data:
        if byte == 0:
            result.append(_B58_ALPHABET[0])
        else:
            break
    return bytes(reversed(result)).decode()


def _load_keypair() -> tuple[bytes, bytes]:
    """Decrypt the Solana keypair from the encrypted blob. Returns (secret_key_64, public_key_32)."""
    encryption_key = os.environ.get("WALLET_ENCRYPTION_KEY")
    if not encryption_key:
        raise RuntimeError("WALLET_ENCRYPTION_KEY not set")

    enc_path = Path(os.environ.get("WALLET_KEY_PATH", _DEFAULT_WALLET_KEY_PATH))
    if not enc_path.exists():
        raise RuntimeError(f"Encrypted wallet file not found: {enc_path}")

    fernet = Fernet(encryption_key.encode())
    try:
        plaintext = fernet.decrypt(enc_path.read_bytes())
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt wallet key — invalid encryption key or corrupted blob") from exc

    if len(plaintext) != 64:
        raise RuntimeError(f"Decrypted keypair must be 64 bytes, got {len(plaintext)}")

    secret_key = plaintext  # 64 bytes: first 32 = private seed, last 32 = public key
    public_key = plaintext[32:]
    return secret_key, public_key


# ---- Minimal Solana transaction parsing (no solders dependency) ----

def _read_compact_u16(data: bytes, offset: int) -> tuple[int, int]:
    """Read a Solana compact-u16 from data at offset. Returns (value, new_offset)."""
    val = 0
    shift = 0
    for i in range(3):
        if offset >= len(data):
            raise ValueError("Unexpected end of data reading compact-u16")
        byte = data[offset]
        offset += 1
        val |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return val, offset
        shift += 7
    raise ValueError("compact-u16 too long")


def _validate_transaction(tx_bytes: bytes, public_key: bytes) -> None:
    """Parse and validate a serialized Solana transaction against the program whitelist.

    Supports both legacy and v0 versioned transactions.
    Rejects transactions where any instruction invokes a program not on the whitelist
    or references an address-lookup-table-resolved program ID.
    """
    if len(tx_bytes) < 2:
        raise ValueError("Transaction too short")

    offset = 0
    prefix = tx_bytes[0]

    is_versioned = (prefix & 0x80) != 0
    if is_versioned:
        version = prefix & 0x7F
        if version != 0:
            raise ValueError(f"Unsupported transaction version: {version}")
        offset = 1

    # -- Read signature count and skip signatures (each 64 bytes) --
    num_sigs, offset = _read_compact_u16(tx_bytes, offset)
    offset += num_sigs * 64

    if offset >= len(tx_bytes):
        raise ValueError("Transaction data truncated after signatures")

    # -- Message header (3 bytes) --
    msg_start = offset
    num_required_sigs = tx_bytes[offset]
    offset += 3  # skip header (num_required_signatures, num_readonly_signed, num_readonly_unsigned)

    # -- Account keys --
    num_accounts, offset = _read_compact_u16(tx_bytes, offset)
    static_account_keys: list[bytes] = []
    for _ in range(num_accounts):
        key = tx_bytes[offset:offset + 32]
        if len(key) != 32:
            raise ValueError("Transaction data truncated in account keys")
        static_account_keys.append(key)
        offset += 32

    # -- Recent blockhash (32 bytes) --
    offset += 32

    # -- Instructions --
    num_instructions, offset = _read_compact_u16(tx_bytes, offset)
    for _ in range(num_instructions):
        program_id_index = tx_bytes[offset]
        offset += 1

        if program_id_index >= num_accounts:
            raise ValueError(
                "Instruction references program ID via address lookup table — "
                "all invoked programs must be in the static account keys"
            )

        program_key = static_account_keys[program_id_index]
        program_id_str = _b58encode(program_key)

        if program_id_str not in ALLOWED_PROGRAMS:
            raise ValueError(f"Program {program_id_str} not in whitelist")

        # Skip account indexes
        num_acct_indexes, offset = _read_compact_u16(tx_bytes, offset)
        offset += num_acct_indexes

        # Skip instruction data
        data_len, offset = _read_compact_u16(tx_bytes, offset)
        offset += data_len

    # -- Verify our public key is a signer --
    signer_keys = static_account_keys[:num_required_sigs]
    if public_key not in signer_keys:
        raise ValueError("Wallet public key is not a required signer on this transaction")


def _sign_message(message_bytes: bytes, secret_key: bytes) -> bytes:
    """Produce an Ed25519 signature over the transaction message."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    # Solana keypair: first 32 bytes are the private seed
    private_key = Ed25519PrivateKey.from_private_bytes(secret_key[:32])
    return private_key.sign(message_bytes)


def _extract_message_bytes(tx_bytes: bytes) -> bytes:
    """Extract the message portion of a serialized transaction (everything after signatures)."""
    offset = 0
    is_versioned = (tx_bytes[0] & 0x80) != 0
    if is_versioned:
        offset = 1

    num_sigs, offset = _read_compact_u16(tx_bytes, offset)
    offset += num_sigs * 64
    return tx_bytes[offset:]


async def _handle_request(
    data: dict,
    secret_key: bytes,
    public_key: bytes,
) -> dict:
    method = data.get("method")
    if method != "sign":
        return {"error": f"Unknown method: {method}"}

    tx_b64 = data.get("transaction")
    if not tx_b64 or not isinstance(tx_b64, str):
        return {"error": "Missing or invalid 'transaction' field (expected base64)"}

    try:
        tx_bytes = base64.b64decode(tx_b64)
    except Exception:
        return {"error": "Invalid base64 in 'transaction' field"}

    try:
        _validate_transaction(tx_bytes, public_key)
    except ValueError as exc:
        log.warning("Transaction rejected: %s", exc)
        return {"error": f"Transaction rejected: {exc}"}

    message_bytes = _extract_message_bytes(tx_bytes)
    signature = _sign_message(message_bytes, secret_key)

    log.info("Signed transaction (%d bytes)", len(tx_bytes))
    return {"signature": base64.b64encode(signature).decode()}


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    secret_key: bytes,
    public_key: bytes,
) -> None:
    peer = writer.get_extra_info("peername") or "unknown"
    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = {"error": "Invalid JSON"}
            else:
                response = await _handle_request(request, secret_key, public_key)

            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
    except ConnectionResetError:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    secret_key, public_key = _load_keypair()
    wallet_address = _b58encode(public_key)
    log.info("Keypair loaded — wallet %s", wallet_address)

    sock_path = Path(SOCKET_PATH)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    server = await asyncio.start_unix_server(
        lambda r, w: _handle_client(r, w, secret_key, public_key),
        path=str(sock_path),
    )
    os.chmod(str(sock_path), 0o660)
    log.info("Listening on %s", sock_path)

    await stop.wait()

    log.info("Signer shutting down")
    server.close()
    await server.wait_closed()
    if sock_path.exists():
        sock_path.unlink()
    log.info("Signer stopped")


if __name__ == "__main__":
    asyncio.run(main())
