# Contributing to MCPRuntime

This document describes how to set up the development environment, run tests, and submit changes.

## Repository layout

| Path | Purpose |
|------|---------|
| `mcpruntime/` | Public package, organized into `core/`, `context/`, and `skills/`. |
| `extensions/` | Optional capabilities such as `extensions/rlm/`. |
| `client/` | Agent helpers, executors, code generation, and compatibility APIs. |
| `config/` | Configuration schema and loader. |
| `server/` | MCP server implementation. |
| `tests/` | Test suite (`unit/`, `integration/`, `e2e/`). |
| `examples/` | Example scripts and usage patterns. |
| `servers/` | Sample MCP-style tool servers. |
| `docs/` | Deeper documentation and design notes. |
| `scripts/` | Development and CI helper scripts. |

## Quick start

```bash
git clone https://github.com/TJKlein/mcpruntime.git
cd mcpruntime
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make env
python scripts/verify_setup.py
make test
```

## Commands

| Command | Description |
|--------|-------------|
| `make install` | Install package |
| `make install-dev` | Install with development dependencies |
| `make env` | Copy `.env.example` to `.env` if missing |
| `make test` | Unit and integration tests |
| `make test-unit` | Unit tests only |
| `make test-e2e` | Live E2E tests |
| `make test-all` | Full test suite |
| `make run-example` | Run `examples/00_simple_api.py` |

## OpenSandbox setup

MCPRuntime uses OpenSandbox as its supported execution backend.

```bash
pip install opensandbox opensandbox-server
opensandbox-server init-config ~/.sandbox.toml --example docker
opensandbox-server start
```

Then verify the local environment:

```bash
python scripts/verify_setup.py
python scripts/check_setup.py
```

## Running tests without Make

```bash
pytest tests/ -v -m "not live"
pytest tests/e2e/ -v
pytest tests/ -v
```

## Environment

Copy `.env.example` to `.env` and set the appropriate variables.

- `OPENAI_API_KEY`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT_NAME`

Do not commit `.env`, `.env.local`, or any file containing credentials.

## Code style

```bash
black .
ruff check .
mypy mcpruntime client config server extensions
```

## Before opening a PR

- Run `python scripts/verify_setup.py`
- Run `pytest tests/ -v -m "not live"`
- Update relevant docs if behavior changed
- Do not commit runtime artifacts such as `.tool_cache.json` or benchmark workspaces
