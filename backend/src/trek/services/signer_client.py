from __future__ import annotations

import asyncio
import json
import logging
import struct

from trek.services.errors import SignerError, SignerUnavailableError

log = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "/run/trek-signer/sign.sock"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0


class SignerClient:
    """Async client that talks to the signer process over a Unix domain socket.

    Wire protocol (length-prefixed JSON):
      Request:  4-byte big-endian length + JSON {"transaction": "<base64>"}
      Response: 4-byte big-endian length + JSON {"signed_transaction": "<base64>"}
                or {"error": "..."}
    """

    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH) -> None:
        self._socket_path = socket_path

    async def sign_transaction(self, unsigned_tx_b64: str) -> str:
        request = json.dumps({"transaction": unsigned_tx_b64}).encode()
        frame = struct.pack(">I", len(request)) + request

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._socket_path),
                timeout=CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            log.error("Cannot reach signer at %s: %s", self._socket_path, exc)
            raise SignerUnavailableError() from exc

        try:
            writer.write(frame)
            await writer.drain()

            length_bytes = await asyncio.wait_for(
                reader.readexactly(4), timeout=READ_TIMEOUT,
            )
            length = struct.unpack(">I", length_bytes)[0]
            body = await asyncio.wait_for(
                reader.readexactly(length), timeout=READ_TIMEOUT,
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, OSError) as exc:
            log.error("Signer communication failed: %s", exc)
            raise SignerError(f"communication failure: {exc}") from exc
        finally:
            writer.close()
            await writer.wait_closed()

        resp = json.loads(body)
        if "error" in resp:
            raise SignerError(resp["error"])

        signed = resp.get("signed_transaction")
        if not signed:
            raise SignerError("response missing signed_transaction field")

        log.info("Transaction signed successfully")
        return signed
