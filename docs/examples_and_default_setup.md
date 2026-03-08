# Examples and Default Setup

## Default setup

- **Config source**: Environment variables and optional `config.yaml`, loaded through `config.loader.load_config()` or `mcpruntime.create_agent()`.
- **Execution backend**: OpenSandbox is the supported backend for sandboxed execution.
- **Development mode**: Subprocess execution is acceptable for local development and benchmarks.
- **Paths**: `WORKSPACE_DIR=./workspace`, `SKILLS_DIR=./skills`, `SERVERS_DIR=./servers`.
- **LLM**: Disabled by default. Enable with environment variables or explicit config.

## Prerequisites

```bash
pip install -e ".[dev]"
pip install opensandbox opensandbox-server
opensandbox-server init-config ~/.sandbox.toml --example docker
opensandbox-server start
```

## Example index

| Example | Purpose | Backend |
|--------|---------|---------|
| `00_simple_api.py` | Minimal `create_agent()` / `execute_task()` usage | OpenSandbox |
| `01-08` | Tools, state, skills, and filesystem workflows | OpenSandbox |
| `09_configuration.py` | Programmatic LLM and state config | OpenSandbox |
| `10-14` | MCP server and client workflows | OpenSandbox |
| `15_recursive_agent.py` | Recursive language model flow | OpenSandbox |
| `16_recursive_agent_with_tools.py` | Recursive flow with tools | OpenSandbox |
| `17_skill_evolution.py` | Self-growing tool library | OpenSandbox |
| `18_streaming.py` | Streaming execution | OpenSandbox |
| `19_replay.py` | Replay and time-travel debugging | OpenSandbox |

## Removed legacy setup

Legacy backend migration notes live under `docs/ARCHIVE_DOCS.md` and other archival docs only.
