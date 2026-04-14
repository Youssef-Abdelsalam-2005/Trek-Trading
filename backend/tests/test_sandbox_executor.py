"""Tests for the strategy sandbox executor.

18 tests covering Docker command flags, execution paths, error handling,
timeout + container kill, OOM detection, invalid JSON, and the runner.py entrypoint.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from trek.sandbox.executor import (
    CPU_LIMIT,
    MEMORY_LIMIT,
    PID_LIMIT,
    SANDBOX_IMAGE,
    TIMEOUT_SECONDS,
    TMPFS_SIZE,
    SandboxError,
    SandboxResult,
    _build_docker_cmd,
    execute,
)


class TestDockerCommandFlags:
    def test_runtime_is_runsc(self):
        cmd = _build_docker_cmd("test-container")
        assert "--runtime=runsc" in cmd

    def test_memory_limit(self):
        cmd = _build_docker_cmd("test-container")
        assert f"--memory={MEMORY_LIMIT}" in cmd

    def test_cpu_limit(self):
        cmd = _build_docker_cmd("test-container")
        assert f"--cpus={CPU_LIMIT}" in cmd

    def test_network_none(self):
        cmd = _build_docker_cmd("test-container")
        assert "--network=none" in cmd

    def test_read_only(self):
        cmd = _build_docker_cmd("test-container")
        assert "--read-only" in cmd

    def test_tmpfs(self):
        cmd = _build_docker_cmd("test-container")
        assert f"--tmpfs=/tmp:size={TMPFS_SIZE}" in cmd

    def test_init_flag(self):
        cmd = _build_docker_cmd("test-container")
        assert "--init" in cmd

    def test_no_new_privileges(self):
        cmd = _build_docker_cmd("test-container")
        assert "--security-opt=no-new-privileges" in cmd

    def test_pids_limit(self):
        cmd = _build_docker_cmd("test-container")
        assert f"--pids-limit={PID_LIMIT}" in cmd

    def test_image_name(self):
        cmd = _build_docker_cmd("test-container")
        assert cmd[-1] == SANDBOX_IMAGE

    def test_interactive_flag(self):
        cmd = _build_docker_cmd("test-container")
        assert "-i" in cmd


class TestExecution:
    @patch("trek.sandbox.executor.subprocess.run")
    def test_successful_execution(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"status": "ok", "result": 42}\n',
            stderr="",
        )
        result = execute("result = 42")
        assert result.status == "ok"
        assert result.result == 42

    @patch("trek.sandbox.executor.subprocess.run")
    def test_strategy_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"status": "error", "error_code": "EXECUTION_ERROR", "detail": "NameError"}\n',
            stderr="",
        )
        result = execute("result = undefined_var")
        assert result.status == "error"
        assert result.error_code == "EXECUTION_ERROR"

    def test_empty_code_raises(self):
        with pytest.raises(SandboxError) as exc_info:
            execute("")
        assert exc_info.value.error_code == "EMPTY_CODE"

    @patch("trek.sandbox.executor.subprocess.run")
    @patch("trek.sandbox.executor._kill_container")
    def test_timeout_kills_container(self, mock_kill, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=60)
        with pytest.raises(SandboxError) as exc_info:
            execute("import time; time.sleep(120)")
        assert exc_info.value.error_code == "TIMEOUT"
        mock_kill.assert_called_once()

    @patch("trek.sandbox.executor.subprocess.run")
    def test_oom_detection(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=137,
            stdout="",
            stderr="",
        )
        with pytest.raises(SandboxError) as exc_info:
            execute("x = bytearray(3 * 1024**3)")
        assert exc_info.value.error_code == "OOM_KILLED"

    @patch("trek.sandbox.executor.subprocess.run")
    def test_invalid_json_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not json at all",
            stderr="",
        )
        with pytest.raises(SandboxError) as exc_info:
            execute("result = 1")
        assert exc_info.value.error_code == "INVALID_JSON"

    @patch("trek.sandbox.executor.subprocess.run")
    def test_container_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="some error",
        )
        with pytest.raises(SandboxError) as exc_info:
            execute("result = 1")
        assert exc_info.value.error_code == "CONTAINER_ERROR"


class TestRunnerDirect:
    """Test runner.py directly (simulating what runs inside the container)."""

    def _run_runner(self, code: str) -> dict:
        import os
        runner_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "docker", "sandbox", "runner.py"
        )
        proc = subprocess.run(
            ["python", runner_path],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return json.loads(proc.stdout.strip())

    def test_runner_success(self):
        result = self._run_runner("result = {'total_return': 0.15}")
        assert result["status"] == "ok"
        assert result["result"]["total_return"] == 0.15

    def test_runner_empty_code(self):
        result = self._run_runner("")
        assert result["status"] == "error"
        assert result["error_code"] == "EMPTY_CODE"

    def test_runner_execution_error(self):
        result = self._run_runner("x = 1/0")
        assert result["status"] == "error"
        assert result["error_code"] == "EXECUTION_ERROR"
        assert "ZeroDivisionError" in result["detail"]

    def test_runner_no_result(self):
        result = self._run_runner("x = 42")
        assert result["status"] == "error"
        assert result["error_code"] == "NO_RESULT"

    def test_runner_non_serializable(self):
        result = self._run_runner("result = object()")
        assert result["status"] == "error"
        assert result["error_code"] == "SERIALIZATION_ERROR"
