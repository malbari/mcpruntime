# MCPRuntime Examples

These examples demonstrate the supported MCPRuntime flow: code generation and execution through OpenSandbox, optional MCP server usage, recursive context handling, and skill accumulation.

## Prerequisites

```bash
pip install -e ".[dev]"
pip install opensandbox opensandbox-server
opensandbox-server init-config ~/.sandbox.toml --example docker
opensandbox-server start
```

Optional for examples that generate code with an LLM:

```bash
cp .env.example .env
# then set OPENAI_API_KEY or AZURE_OPENAI_* variables
```

## Recommended starting points

| Example | Purpose |
|--------|---------|
| `00_simple_api.py` | Simplest `create_agent()` / `execute_task()` usage |
| `01_basic_tool_call.py` | Basic tool discovery and invocation |
| `05_state_persistence.py` | Persisting workspace state across runs |
| `06_skills.py` | Reusing saved skills |
| `15_recursive_agent.py` | Recursive language model pattern |
| `17_skill_evolution.py` | Skill accumulation over time |
| `18_streaming.py` | Streaming execution output |
| `19_replay.py` | Replay and time-travel debugging |

## Running examples

From the repository root:

```bash
python examples/00_simple_api.py
python examples/06_skills.py
python examples/15_recursive_agent.py
```

## MCP server examples

Examples `10_mcp_server.py`, `11_mcp_server_client.py`, `12_mcp_client_example.py`, and `14_mcp_statefulness.py` demonstrate MCP server/client flows.

Run the server from the repository root:

```bash
python -m server.mcp_server
```

## Setup verification

```bash
python scripts/check_setup.py
python scripts/verify_setup.py
```

## Notes

- OpenSandbox is the supported execution backend.
- Subprocess mode exists for development and benchmark baselines.
- Legacy backend-specific examples have been removed from the active example set.
