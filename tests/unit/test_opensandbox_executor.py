"""Unit tests for OpenSandboxExecutor."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from config.schema import ExecutionConfig, GuardrailConfig, OptimizationConfig
from client.base import ExecutionResult


@pytest.fixture
def exec_config(tmp_path):
    """Execution config pointing at a temp workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    servers = tmp_path / "servers"
    servers.mkdir()
    skills = tmp_path / "skills"
    skills.mkdir()
    return ExecutionConfig(
        sandbox_type="opensandbox",
        workspace_dir=str(workspace),
        servers_dir=str(servers),
        skills_dir=str(skills),
        opensandbox_domain="localhost:8080",
        opensandbox_image="python:3.11",
    )


@pytest.fixture
def guardrail_config():
    return GuardrailConfig(enabled=False)


@pytest.fixture
def optimization_config():
    return OptimizationConfig(enabled=True)


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

def test_execute_raises_import_error_when_sdk_missing(exec_config, guardrail_config, optimization_config):
    """OpenSandboxExecutor raises ImportError when the opensandbox SDK is not installed."""
    # Temporarily pretend the SDK is not installed
    import client.opensandbox_executor as mod
    original_sandbox = mod.Sandbox

    try:
        mod.Sandbox = None
        from client.opensandbox_executor import OpenSandboxExecutor
        executor = OpenSandboxExecutor(exec_config, guardrail_config, optimization_config)
        with pytest.raises(ImportError, match="opensandbox is not installed"):
            executor.execute("print('hello')")
    finally:
        mod.Sandbox = original_sandbox


# ---------------------------------------------------------------------------
# Guardrail validation
# ---------------------------------------------------------------------------

def test_execute_fails_on_invalid_code(exec_config, optimization_config):
    """Guardrail validation fires before any sandbox interaction."""
    guardrails = GuardrailConfig(enabled=True, blocked_patterns=["import os"])

    import client.opensandbox_executor as mod
    # Ensure SDK is seen as available by giving it a dummy value
    if mod.Sandbox is None:
        pytest.skip("opensandbox SDK not installed; skipping live-path test")

    from client.opensandbox_executor import OpenSandboxExecutor
    executor = OpenSandboxExecutor(exec_config, guardrails, optimization_config)

    result, output, error = executor.execute("import os\nprint(os.getcwd())")
    assert result == ExecutionResult.FAILURE
    assert output is None
    assert error is not None


# ---------------------------------------------------------------------------
# Successful execution (fully mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_async_success(exec_config, guardrail_config, optimization_config, tmp_path):
    """_execute_async returns (output, None) when OpenSandbox runs code successfully."""
    from client.opensandbox_executor import OpenSandboxExecutor

    executor = OpenSandboxExecutor(exec_config, guardrail_config, optimization_config)

    # Build a mock stdout log entry
    mock_log_entry = MagicMock()
    mock_log_entry.text = "Hello OpenSandbox!\n"

    mock_exec_result = MagicMock()
    mock_exec_result.logs.stdout = [mock_log_entry]
    mock_exec_result.logs.stderr = []

    # Mock Sandbox.create as async context manager
    mock_sandbox = AsyncMock()
    mock_sandbox.commands.run = AsyncMock(return_value=mock_exec_result)
    mock_sandbox.files.write_files = AsyncMock()
    mock_sandbox.kill = AsyncMock()
    mock_sandbox.__aenter__ = AsyncMock(return_value=mock_sandbox)
    mock_sandbox.__aexit__ = AsyncMock(return_value=False)

    mock_create = AsyncMock(return_value=mock_sandbox)

    import client.opensandbox_executor as mod
    with patch.object(mod, "Sandbox") as MockSandbox, \
         patch.object(mod, "ConnectionConfig") as MockConnCfg, \
         patch.object(mod, "WriteEntry", MagicMock(side_effect=lambda **kw: kw)):
        MockSandbox.create = mock_create
        MockConnCfg.return_value = MagicMock()

        output, error = await executor._execute_async("print('Hello OpenSandbox!')")

    assert error is None
    assert "Hello OpenSandbox!" in output


def test_execute_success_via_sync(exec_config, guardrail_config, optimization_config, tmp_path):
    """execute() returns SUCCESS and captured output when the sandbox runs code successfully."""
    from client.opensandbox_executor import OpenSandboxExecutor

    executor = OpenSandboxExecutor(exec_config, guardrail_config, optimization_config)

    expected_output = "Hello from OpenSandbox\n"

    mock_log_entry = MagicMock()
    mock_log_entry.text = expected_output

    mock_exec_result = MagicMock()
    mock_exec_result.logs.stdout = [mock_log_entry]
    mock_exec_result.logs.stderr = []

    mock_sandbox = AsyncMock()
    mock_sandbox.commands.run = AsyncMock(return_value=mock_exec_result)
    mock_sandbox.files.write_files = AsyncMock()
    mock_sandbox.kill = AsyncMock()
    mock_sandbox.__aenter__ = AsyncMock(return_value=mock_sandbox)
    mock_sandbox.__aexit__ = AsyncMock(return_value=False)

    import client.opensandbox_executor as mod
    with patch.object(mod, "Sandbox") as MockSandbox, \
         patch.object(mod, "ConnectionConfig"), \
         patch.object(mod, "WriteEntry", MagicMock(side_effect=lambda **kw: kw)):
        MockSandbox.create = AsyncMock(return_value=mock_sandbox)

        result, output, error = executor.execute("print('Hello from OpenSandbox')")

    assert result == ExecutionResult.SUCCESS
    assert expected_output in output
    assert error is None
