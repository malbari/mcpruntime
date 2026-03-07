"""Live E2E tests for AgentHelper using OpenSandbox and real LLM."""

import pytest
import os
from pathlib import Path
from client.agent_helper import AgentHelper
from client.opensandbox_executor import OpenSandboxExecutor
from client.filesystem_helpers import FilesystemHelper
from client.base import ExecutionResult
from config.schema import ExecutionConfig


@pytest.mark.live
class TestVanillaOpenSandboxLive:

    @pytest.fixture
    def agent_helper(self, mock_config, temp_workspace, temp_servers, live_llm_client, live_llm_model_name, live_app_config):
        """Create a standard AgentHelper with OpenSandbox and live LLM config from .env."""
        fs_helper = FilesystemHelper(
            workspace_dir=str(temp_workspace),
            servers_dir=str(temp_servers),
            skills_dir=str(Path(temp_workspace) / "skills"),
        )
        # Use temp paths in execution config so executor pushes same workspace/servers/skills as agent
        execution = ExecutionConfig(
            workspace_dir=str(temp_workspace),
            servers_dir=str(temp_servers),
            skills_dir=str(Path(temp_workspace) / "skills"),
            timeout=mock_config.execution.timeout,
            sandbox_type="opensandbox",
        )
        executor = OpenSandboxExecutor(
            execution_config=execution
        )

        # Use live LLM config from .env so CodeGenerator gets api_key, endpoint, etc.
        helper = AgentHelper(
            fs_helper=fs_helper,
            executor=executor,
            llm_config=live_app_config.llm
        )

        helper.code_generator._llm_client = live_llm_client
        helper.code_generator._model_name = live_llm_model_name

        return helper

    def test_live_vanilla_calculation(self, agent_helper):
        """Verify standard agent can do math using OpenSandbox and Real LLM."""
        task = "Calculate the square root of 144 and multiply by 10"

        print("\n[Live] Executing Vanilla OpenSandbox task...")
        status, output, error = agent_helper.execute_task(task)

        assert error is None
        assert status == ExecutionResult.SUCCESS
        assert "120" in str(output)
