from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SANDBOX_SCRIPT = str(Path(__file__).resolve().parent.parent / "sandbox_script.py")
TIMEOUT_SECONDS = 60


class SandboxError(Exception):
    pass


async def run_in_sandbox(
    strategy_code: str,
    ohlcv_json: str,
    *,
    fee_rate: float = 0.001,
    slippage: float = 0.0005,
    timeout: int = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute strategy code in a subprocess and return backtest metrics.

    Sends strategy code + OHLCV data via stdin as JSON. The subprocess runs
    vectorbt backtesting and returns metrics as JSON on stdout. This maintains
    a process boundary (C4) until the real Docker/gVisor sandbox from Step 17
    is available.
    """
    input_payload = json.dumps({
        "strategy_code": strategy_code,
        "ohlcv_data": ohlcv_json,
        "fee_rate": fee_rate,
        "slippage": slippage,
    })

    proc = await asyncio.create_subprocess_exec(
        sys.executable, SANDBOX_SCRIPT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input_payload.encode()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SandboxError(f"Sandbox timed out after {timeout}s")

    if proc.returncode != 0:
        err_msg = stderr.decode(errors="replace").strip()[-500:]
        raise SandboxError(f"Sandbox exited with code {proc.returncode}: {err_msg}")

    try:
        return json.loads(stdout.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SandboxError(f"Sandbox returned invalid JSON: {exc}")
