"""Host-side sandbox executor — runs strategy code in a gVisor-sandboxed Docker container."""
from __future__ import annotations

import json
import logging
import subprocess
import uuid
from dataclasses import dataclass

log = logging.getLogger(__name__)

SANDBOX_IMAGE = "trek-sandbox:latest"
TIMEOUT_SECONDS = 60
MEMORY_LIMIT = "2g"
CPU_LIMIT = "1"
PID_LIMIT = 256
TMPFS_SIZE = "256m"


class SandboxError(Exception):
    def __init__(self, error_code: str, detail: str):
        self.error_code = error_code
        self.detail = detail
        super().__init__(f"{error_code}: {detail}")


@dataclass
class SandboxResult:
    status: str
    result: object = None
    error_code: str | None = None
    detail: str | None = None


def _build_docker_cmd(container_name: str) -> list[str]:
    return [
        "docker", "run",
        "--rm",
        "--name", container_name,
        "--runtime=runsc",
        f"--memory={MEMORY_LIMIT}",
        f"--cpus={CPU_LIMIT}",
        "--network=none",
        "--read-only",
        f"--tmpfs=/tmp:size={TMPFS_SIZE}",
        "--init",
        "--security-opt=no-new-privileges",
        f"--pids-limit={PID_LIMIT}",
        "-i",
        SANDBOX_IMAGE,
    ]


def execute(code: str, *, timeout: int = TIMEOUT_SECONDS) -> SandboxResult:
    if not code.strip():
        raise SandboxError("EMPTY_CODE", "No code provided")

    container_name = f"trek-sandbox-{uuid.uuid4().hex[:12]}"
    cmd = _build_docker_cmd(container_name)

    try:
        proc = subprocess.run(
            cmd,
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _kill_container(container_name)
        raise SandboxError("TIMEOUT", f"Strategy execution exceeded {timeout}s timeout")

    if proc.returncode == 137:
        raise SandboxError("OOM_KILLED", f"Container killed (OOM or signal 9), memory limit: {MEMORY_LIMIT}")

    if proc.returncode != 0:
        stderr = proc.stderr.strip()[:500]
        raise SandboxError("CONTAINER_ERROR", f"Container exited with code {proc.returncode}: {stderr}")

    stdout = proc.stdout.strip()
    if not stdout:
        raise SandboxError("EMPTY_OUTPUT", "Container produced no output")

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SandboxError("INVALID_JSON", f"Container output is not valid JSON: {exc}")

    status = parsed.get("status")
    if status == "ok":
        return SandboxResult(status="ok", result=parsed.get("result"))
    elif status == "error":
        return SandboxResult(
            status="error",
            error_code=parsed.get("error_code"),
            detail=parsed.get("detail"),
        )
    else:
        raise SandboxError("INVALID_OUTPUT", f"Unexpected status in container output: {status}")


def _kill_container(name: str) -> None:
    try:
        subprocess.run(
            ["docker", "kill", name],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        log.warning("Failed to kill container %s", name)

    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass
