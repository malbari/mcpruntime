#!/usr/bin/env python
"""Generate filesystem stub files from a live MCP server.

Questo script implementa il meccanismo documentato in servers/README.md:
  "To generate tool files from actual MCP servers, use the tool generation script"

Funzionamento:
  1. Si connette al server MCP via fastmcp (list_tools)
  2. Per ogni tool, genera un file stub Python in servers/<server_name>/<tool>.py
  3. Genera servers/<server_name>/__init__.py con i re-export

Gli stub generati usano `call_mcp_tool` da `client.mcp_client`, seguendo il pattern
documentato da Anthropic (https://www.anthropic.com/engineering/code-execution-with-mcp):
il codice generato dall'LLM importa le funzioni da servers/, e OpenSandboxExecutor
carica quei file nel container via sandbox.files.write_files().

Uso:
    python scripts/generate_tool_files.py \\
        --mcp-url http://localhost:3001/mcp \\
        --server-name api-to-mcp \\
        --servers-dir ./servers

    # Forza la rigenerazione anche se gli stub esistono già:
    python scripts/generate_tool_files.py --mcp-url ... --overwrite

Prerequisiti:
    pip install fastmcp
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Any, Optional


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    """Converte un nome MCP (es. 'news-get') in un identificatore Python valido."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if s and s[0].isdigit():
        s = "_" + s
    return s


def _derive_server_name(mcp_url: str) -> str:
    """Deriva un nome server dall'URL MCP se non specificato."""
    host = mcp_url.split("//")[-1].split("/")[0]   # es. "localhost:3001"
    return _safe_name(host.replace(".", "_"))


def _json_type_to_python(prop: dict) -> str:
    """Mappa un tipo JSON Schema al tipo hint Python corrispondente."""
    mapping = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list",
        "object": "dict",
    }
    return mapping.get(prop.get("type", ""), "Any")


def _build_stub_source(
    tool_name: str,
    safe_name: str,
    description: str,
    input_schema: dict,
    server_name: str,
) -> str:
    """Genera il codice sorgente dello stub per un tool MCP.

    Lo stub:
    - Ha la firma Python corretta (tipi e default dall'inputSchema)
    - Chiama call_mcp_tool(server_name, tool_name, args) da client.mcp_client
    - Include docstring con nome tool originale e descrizione
    """
    props: dict = input_schema.get("properties", {})
    required: set = set(input_schema.get("required", []))

    params: list[str] = []
    call_args: dict[str, str] = {}
    has_optional = False

    for param_name, prop in props.items():
        py_type = _json_type_to_python(prop)
        default = prop.get("default")
        examples = prop.get("examples") or []
        example = examples[0] if examples else None

        if param_name in required:
            params.append(f"{param_name}: {py_type}")
        else:
            has_optional = True
            if default is not None:
                params.append(f"{param_name}: {py_type} = {default!r}")
            elif example is not None:
                params.append(f"{param_name}: {py_type} = {example!r}")
            else:
                params.append(f"{param_name}: Optional[{py_type}] = None")

        call_args[param_name] = param_name

    params_str = ", ".join(params) if params else ""
    call_args_str = (
        "{"
        + ", ".join(f'"{k}": {v}' for k, v in call_args.items())
        + "}"
    )

    typing_imports = "from typing import Any, Optional" if has_optional else "from typing import Any"

    return f'''\
"""Stub per il tool MCP '{tool_name}' su server '{server_name}'.

{description or f"Chiama il tool '{tool_name}' sul server MCP '{server_name}'."}

Generato automaticamente da scripts/generate_tool_files.py — non modificare.
Riferimento: https://www.anthropic.com/engineering/code-execution-with-mcp
"""
{typing_imports}
from client.mcp_client import call_mcp_tool


def {safe_name}({params_str}) -> Any:
    """{description or f"Chiama {tool_name} su {server_name}."}"""
    return call_mcp_tool(
        "{server_name}",
        "{tool_name}",
        {call_args_str},
    )
'''


def _build_init_source(server_name: str, entries: list[tuple[str, str]]) -> str:
    """Genera __init__.py che esporta tutti i tool dello stesso server."""
    imports = "\n".join(f"from .{safe} import {safe}" for safe, _ in entries)
    all_list = repr([safe for safe, _ in entries])
    return f'''\
"""Stub package per il server MCP '{server_name}'.

Generato automaticamente da scripts/generate_tool_files.py.
Importa e ri-esporta tutti i tool del server.
"""
{imports}

__all__ = {all_list}
'''


# ── Core async logic ───────────────────────────────────────────────────────

async def generate_stubs(
    mcp_url: str,
    server_name: str,
    servers_dir: Path,
    overwrite: bool = False,
    verbose: bool = True,
) -> list[tuple[str, str]]:
    """Connetti al server MCP, scopri i tool, scrivi gli stub su disco.

    Args:
        mcp_url: URL del server MCP (streamable_http transport)
        server_name: nome della directory da creare in servers/
        servers_dir: path della directory servers/ del progetto
        overwrite: se True, sovrascrive stub già esistenti
        verbose: stampa avanzamento

    Returns:
        Lista di (safe_name, original_tool_name) per i tool generati
    """
    try:
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
    except ImportError:
        print("ERRORE: fastmcp non installato. Esegui: pip install fastmcp", file=sys.stderr)
        sys.exit(1)

    url = mcp_url.rstrip("/") + "/"
    if verbose:
        print(f"[generate] Connessione a {url} ...")

    async with Client(StreamableHttpTransport(url=url)) as client:
        tools = await client.list_tools()

    if verbose:
        print(f"[generate] {len(tools)} tool trovati")

    server_dir = servers_dir / server_name
    server_dir.mkdir(parents=True, exist_ok=True)

    entries: list[tuple[str, str]] = []

    for t in tools:
        tool_name: str = getattr(t, "name", "")
        description: str = (getattr(t, "description", "") or "").strip()
        input_schema: dict = (
            getattr(t, "inputSchema", None)
            or getattr(t, "input_schema", None)
            or {}
        )

        safe = _safe_name(tool_name)
        stub_file = server_dir / f"{safe}.py"

        if stub_file.exists() and not overwrite:
            if verbose:
                print(f"[generate]   · {stub_file.name} già esistente (usa --overwrite per rigenerare)")
            entries.append((safe, tool_name))
            continue

        source = _build_stub_source(tool_name, safe, description, input_schema, server_name)
        stub_file.write_text(source, encoding="utf-8")
        entries.append((safe, tool_name))

        if verbose:
            rel = stub_file.relative_to(servers_dir.parent)
            print(f"[generate]   ✓ {rel}")

    # __init__.py
    init_file = server_dir / "__init__.py"
    if not init_file.exists() or overwrite:
        init_file.write_text(_build_init_source(server_name, entries), encoding="utf-8")
        if verbose:
            rel = init_file.relative_to(servers_dir.parent)
            print(f"[generate]   ✓ {rel}")
    elif verbose:
        print(f"[generate]   · __init__.py già esistente")

    if verbose:
        print(f"[generate] Completato — {len(entries)} stub in '{server_dir}'")

    return entries


# ── CLI ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera filesystem stub da un server MCP live.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python scripts/generate_tool_files.py --mcp-url http://localhost:3001/mcp
  python scripts/generate_tool_files.py \\
      --mcp-url http://localhost:3001/mcp \\
      --server-name api-to-mcp \\
      --servers-dir ./servers \\
      --overwrite
""",
    )
    parser.add_argument(
        "--mcp-url",
        required=True,
        help="URL del server MCP (es. http://localhost:3001/mcp)",
    )
    parser.add_argument(
        "--server-name",
        default=None,
        help="Nome della directory server in servers/ (default: derivato dall'URL)",
    )
    parser.add_argument(
        "--servers-dir",
        default=None,
        help="Directory servers/ del progetto (default: ./servers relativo a pyproject.toml)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sovrascrivi stub esistenti",
    )
    args = parser.parse_args()

    mcp_url: str = args.mcp_url
    server_name: str = args.server_name or _derive_server_name(mcp_url)

    # Trova la root del progetto (dove c'è pyproject.toml / .git)
    if args.servers_dir:
        servers_dir = Path(args.servers_dir).resolve()
    else:
        root = Path(__file__).resolve().parent.parent  # scripts/../ = project root
        servers_dir = root / "servers"

    print(f"[generate] Server name  : {server_name}")
    print(f"[generate] Servers dir  : {servers_dir}")
    print(f"[generate] MCP URL      : {mcp_url}")

    asyncio.run(
        generate_stubs(
            mcp_url=mcp_url,
            server_name=server_name,
            servers_dir=servers_dir,
            overwrite=args.overwrite,
            verbose=True,
        )
    )


if __name__ == "__main__":
    main()
