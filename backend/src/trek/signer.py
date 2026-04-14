import asyncio
import base64
import json
import logging
import os
import signal
import struct
from pathlib import Path

from cryptography.fernet import Fernet
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [signer] %(message)s")
log = logging.getLogger(__name__)

SOCKET_PATH = os.environ.get("SIGNER_SOCKET_PATH", "/run/trek-signer/sign.sock")
ENCRYPTED_KEY_PATH = os.environ.get(
    "SIGNER_ENCRYPTED_KEY_PATH", "/etc/trek-signer/wallet.key.enc"
)

ALLOWED_PROGRAMS: frozenset[str] = frozenset({
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter Aggregator v6
    "11111111111111111111111111111111",                  # System Program
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",     # SPL Token Program
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",    # SPL Associated Token Account
    "T1pyyaTNZsKv2WcRAB8oVnk93mLJw2XzjtVYqCsaHqt",    # Jito Tip Program
    "ComputeBudget111111111111111111111111111111",       # Compute Budget Program
})


def load_keypair() -> Keypair:
    encryption_key = os.environ.get("WALLET_ENCRYPTION_KEY")
    if not encryption_key:
        raise RuntimeError("WALLET_ENCRYPTION_KEY not set")

    encrypted_blob = Path(ENCRYPTED_KEY_PATH).read_bytes()
    fernet = Fernet(encryption_key.encode())
    raw_key = fernet.decrypt(encrypted_blob)

    return Keypair.from_bytes(raw_key)


def validate_transaction(tx: VersionedTransaction) -> None:
    for ix in tx.message.instructions():
        account_keys = tx.message.account_keys()
        program_id = str(account_keys[ix.program_id_index])
        if program_id not in ALLOWED_PROGRAMS:
            raise ValueError(f"Disallowed program: {program_id}")


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    keypair: Keypair,
) -> None:
    peer = writer.get_extra_info("peername") or "unknown"
    try:
        length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=10.0)
        length = struct.unpack(">I", length_bytes)[0]
        if length > 64 * 1024:
            raise ValueError(f"Payload too large: {length} bytes")

        body = await asyncio.wait_for(reader.readexactly(length), timeout=10.0)
        req = json.loads(body)

        tx_b64 = req.get("transaction")
        if not tx_b64:
            raise ValueError("Missing 'transaction' field")

        tx_bytes = base64.b64decode(tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        validate_transaction(tx)

        signed_tx = VersionedTransaction.populate(tx.message, [keypair.sign_message(bytes(tx.message))])
        signed_b64 = base64.b64encode(bytes(signed_tx)).decode()

        resp = json.dumps({"signed_transaction": signed_b64}).encode()
        log.info("Signed transaction for %s", peer)

    except Exception as exc:
        log.warning("Sign request failed from %s: %s", peer, exc)
        resp = json.dumps({"error": str(exc)}).encode()

    frame = struct.pack(">I", len(resp)) + resp
    writer.write(frame)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    keypair = load_keypair()
    log.info("Loaded wallet: %s", keypair.pubkey())

    socket_path = Path(SOCKET_PATH)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, keypair),
        path=str(socket_path),
    )
    os.chmod(str(socket_path), 0o660)

    log.info("Signer started — listening on %s", socket_path)

    await stop.wait()

    log.info("Signer shutting down")
    server.close()
    await server.wait_closed()
    if socket_path.exists():
        socket_path.unlink()


if __name__ == "__main__":
    asyncio.run(main())
