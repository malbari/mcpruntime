#!/usr/bin/env python3
"""
Demo — create_agent() nativo + OpenSandbox REST API (porta 44772)
====================================================================
Usa i componenti del framework MCPRuntime in modo canonico.

Architettura:
  - OpenSandbox execd (porta 44772): esegue codice via POST /code (NDJSON).
    I file vengono uploadati nel container via:
      POST /directories  — crea le directory necessarie
      POST /files/upload — multipart upload (metadata JSON + file binario)
  - create_agent() gestisce FilesystemHelper, ToolSelector, CodeGenerator.
  - Un proxy locale instrada le chiamate MCP dal container all'host.

Prerequisiti (gestiti da run_demo.sh):
  - Virtual env con: fastmcp openai python-dotenv httpx litellm
  - Stub già presenti in servers/<server>/ (generati da generate_tool_files.py)
  - OpenSandbox execd porta 44772 accessibile
"""

import asyncio
import json
import logging
import os
import re
import socketserver
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional

# Silence HuggingFace/sentence-transformers noise before any import triggers them
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# ── Bootstrap path ─────────────────────────────────────────────────────────
_DEMO_DIR = Path(__file__).parent.resolve()
_ROOT = _DEMO_DIR.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_DEMO_DIR / ".env")

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("demo")
# Suppress noisy third-party loggers
logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)

# ── Config ───────────────────────────────────────────────────────────────────
SANDBOX_HOST    = os.environ.get("SANDBOX_HOST", "host.docker.internal")
OPENSANDBOX_URL = os.environ.get("OPENSANDBOX_URL", "http://localhost:44772")
PROMPT          = "Mi dici le ultime 5 news sul turismo?"
SERVERS_DIR     = _ROOT / "servers"

# Lista server MCP — caricata da demo/servers.json (unico punto di configurazione)
_SERVERS_FILE   = _DEMO_DIR / "servers.json"
SERVERS_CONFIG: list[dict] = json.loads(_SERVERS_FILE.read_text(encoding="utf-8"))["servers"]
_SERVERS_BY_NAME: dict[str, str] = {}  # name → url; popolato da _start_proxy()


# ══════════════════════════════════════════════════════════════════════════════
#  1 — Proxy MCP  (container → host → server MCP)
#      Stessa architettura di run_demo.py: il codice nel container chiama
#      http://host.docker.internal:<porta>/call-tool  →  proxy  →  MCP server.
# ══════════════════════════════════════════════════════════════════════════════

async def _mcp_call(tool: str, args: dict, url: str) -> Any:
    """Chiama un tool sul server MCP via fastmcp."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    async with Client(StreamableHttpTransport(url=url.rstrip("/") + "/")) as c:
        raw = await c.call_tool(tool, args)
    # fastmcp 3.x → list[TextContent]
    item = (raw[0] if isinstance(raw, list) and raw
            else getattr(raw, "content", [None])[0] if hasattr(raw, "content") and raw.content
            else raw)
    text = getattr(item, "text", None)
    try:
        return json.loads(text) if text else raw
    except (json.JSONDecodeError, TypeError):
        return text or raw


class _ProxyHandler(BaseHTTPRequestHandler):
    """Riceve POST /call-tool dal container, chiama MCP, risponde JSON."""

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            p = json.loads(body)
            server_name = p.get("server", "")
            server_url  = _SERVERS_BY_NAME.get(server_name)
            if not server_url:
                raise ValueError(f"Server MCP sconosciuto: {server_name!r}")
            logger.info(f"[Proxy] → {server_name}/{p['tool']}({json.dumps(p.get('args',{}))[:80]})")
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_mcp_call(p["tool"], p.get("args", {}), server_url))
            finally:
                loop.close()
            _preview = str(result)
            if len(_preview) > 200:
                _preview = _preview[:200] + "..."
            logger.info(f"[Proxy] ← MCP: {_preview}")
            resp = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        except Exception as exc:
            logger.error(f"[Proxy] Errore: {exc}")
            err = json.dumps({"error": str(exc)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def log_message(self, fmt, *args):
        logger.debug(f"[Proxy HTTP] {fmt % args}")


def _start_proxy(servers_config: list[dict]) -> tuple[socketserver.TCPServer, int]:
    """Avvia il proxy e popola _SERVERS_BY_NAME con le URL da servers.json."""
    _SERVERS_BY_NAME.clear()
    _SERVERS_BY_NAME.update({s["name"]: s["url"] for s in servers_config})
    srv = socketserver.TCPServer(("", 0), _ProxyHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for name, url in _SERVERS_BY_NAME.items():
        logger.info(f"[STEP 1] Proxy: {name} → {url}")
    logger.info(f"[STEP 1] Proxy MCP avviato sulla porta {port}")
    return srv, port


# ══════════════════════════════════════════════════════════════════════════════
#  2 — Upload workspace nel container via execd API
#      POST /directories  — crea le directory (mkdir -p)
#      POST /files/upload — multipart: metadata (JSON file-part) + file (binary)
# ══════════════════════════════════════════════════════════════════════════════

def _proxy_client_src(port: int, sandbox_host: str) -> str:
    """Sorgente Python di client/mcp_client.py proxy-aware da iniettare nel container."""
    return (
        '"""call_mcp_tool proxy-aware — iniettato da demo."""\n'
        "import json, urllib.request\nfrom typing import Any\n\n"
        f"_PROXY_PORT = {port}\n"
        f"_SANDBOX_HOST = {sandbox_host!r}\n\n"
        "def call_mcp_tool(\n"
        "    server_name: str, tool_name: str,\n"
        "    parameters: dict, server_configs=None\n"
        ") -> Any:\n"
        "    _url = f'http://{_SANDBOX_HOST}:{_PROXY_PORT}/call-tool'\n"
        "    _args = {k: v for k, v in parameters.items() if v is not None}\n"
        "    _body = json.dumps({'server': server_name, 'tool': tool_name, 'args': _args}).encode()\n"
        "    _req = urllib.request.Request(\n"
        "        _url, data=_body,\n"
        "        headers={'Content-Type': 'application/json'},\n"
        "        method='POST',\n"
        "    )\n"
        "    with urllib.request.urlopen(_req, timeout=30) as _r:\n"
        "        return json.loads(_r.read())\n"
    )


def _upload_workspace(
    proxy_port: int,
    sandbox_host: str,
    servers_dir: Path,
    server_names: list[str],
    base_url: str,
) -> None:
    """Crea directory e uploada file nel container via execd API.

    1. POST /directories — crea /workspace/client e /workspace/servers/<name>
    2. POST /files/upload — multipart con coppie (metadata, file) per ogni file
    """
    import httpx

    # Raccoglie tutti i file da uploadare: (path_container, contenuto_str)
    files_to_upload: list[tuple[str, str]] = [
        ("/workspace/client/__init__.py", '"""Client module."""\n'),
        ("/workspace/client/mcp_client.py", _proxy_client_src(proxy_port, sandbox_host)),
        ("/workspace/servers/__init__.py", "\n"),
    ]
    for server_name in server_names:
        stub_dir = servers_dir / server_name
        if not stub_dir.exists():
            continue
        files_to_upload.append((f"/workspace/servers/{server_name}/__init__.py", "\n"))
        for stub_file in sorted(stub_dir.glob("*.py")):
            content = stub_file.read_text(encoding="utf-8")
            files_to_upload.append((f"/workspace/servers/{server_name}/{stub_file.name}", content))

    with httpx.Client(timeout=30) as client:
        # 1. Crea directory (mkdir -p)
        dirs_payload: dict[str, dict] = {
            "/workspace/client": {"mode": 755},
            "/workspace/servers": {"mode": 755},
        }
        for sn in server_names:
            dirs_payload[f"/workspace/servers/{sn}"] = {"mode": 755}
        resp = client.post(f"{base_url}/directories", json=dirs_payload)
        resp.raise_for_status()
        logger.debug("[Upload] Directory create: %s", list(dirs_payload))

        # 2. Upload file — un'unica richiesta multipart con N coppie (metadata, file)
        # metadata deve essere file-part (con filename) perché Go usa form.File["metadata"]
        parts: list[tuple] = []
        for path, content in files_to_upload:
            meta = json.dumps({"path": path, "mode": 644}).encode()
            parts.append(("metadata", ("meta.json", meta, "application/json")))
            parts.append(("file", (Path(path).name, content.encode(), "text/plain")))
        resp = client.post(f"{base_url}/files/upload", files=parts)
        resp.raise_for_status()
        logger.info("[Upload] %d file uploadati nel container", len(files_to_upload))


# ══════════════════════════════════════════════════════════════════════════════
#  3 — Esecuzione REST execd  POST /code  (NDJSON streaming response)
# ══════════════════════════════════════════════════════════════════════════════

def _reset_kernel(base_url: str) -> None:
    """Elimina tutti i contesti Python in execd (reset kernel Jupyter).

    Necessario prima di ogni esecuzione per evitare che un kernel rimasto
    occupato da una run precedente restituisca RUNTIME_ERROR.
    """
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/code/contexts",
        headers={"Content-Type": "application/json"},
        method="DELETE",
    )
    req.add_unredirected_header("X-Language", "python")
    try:
        urllib.request.urlopen(req, timeout=10)
        logger.debug("[execd] Kernel Python resettato")
    except Exception as exc:
        logger.debug("[execd] Reset kernel (ignorabile): %s", exc)


def _parse_ndjson(base_url: str, code: str) -> tuple[Optional[str], Optional[str]]:
    """Esegue POST /code e raccoglie stdout/stderr da NDJSON. Ritorna (stdout, stderr)."""
    payload = json.dumps({"context": {"language": "python"}, "code": code}).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/code",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    runtime_error: Optional[str] = None
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Kernel busy: {"code":"RUNTIME_ERROR","message":"...session is busy"}
                if msg.get("code") == "RUNTIME_ERROR":
                    runtime_error = msg.get("message", "session is busy")
                    break
                t = msg.get("type", "")
                if t == "stdout":
                    stdout_parts.append(msg.get("text", ""))
                elif t == "stderr":
                    stderr_parts.append(msg.get("text", ""))
                elif t == "error":
                    err = msg.get("error", {})
                    tb = err.get("traceback", [])
                    text = "\n".join(tb) if tb else f"{err.get('ename', 'Error')}: {err.get('evalue', '')}"
                    stderr_parts.append(text)
    except Exception as exc:
        return None, str(exc)
    if runtime_error:
        return None, f"RUNTIME_ERROR: {runtime_error}"
    return "".join(stdout_parts) or None, "".join(stderr_parts) or None


def _rest_execute(code: str, base_url: str = "http://localhost:44772") -> tuple[Optional[str], Optional[str]]:
    """Reset kernel, invia codice a execd via POST /code, riprova una volta se busy."""
    _reset_kernel(base_url)
    stdout, stderr = _parse_ndjson(base_url, code)
    if stderr and stderr.startswith("RUNTIME_ERROR"):
        logger.warning("[execd] Kernel occupato, reset e nuovo tentativo ...")
        _reset_kernel(base_url)
        stdout, stderr = _parse_ndjson(base_url, code)
    return stdout, stderr


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    from mcpruntime import create_agent

    logger.info("=" * 60)
    logger.info("Demo — create_agent() + execd REST (porta 44772)")
    logger.info("=" * 60)

    # ── STEP 1: Proxy ─────────────────────────────────────────────────────
    proxy_srv, proxy_port = _start_proxy(SERVERS_CONFIG)

    # ── STEP 2: Stub (idempotente, per ogni server in servers.json) ────────
    sys.path.insert(0, str(_ROOT / "scripts"))
    from generate_tool_files import generate_stubs  # type: ignore[import]
    for _srv in SERVERS_CONFIG:
        _stub_dir = SERVERS_DIR / _srv["name"]
        _py_stubs = (
            [f for f in _stub_dir.glob("*.py") if f.name != "__init__.py"]
            if _stub_dir.exists() else []
        )
        if not _py_stubs:
            logger.info("[STEP 2] Generazione stub '%s' da %s ...", _srv["name"], _srv["url"])
            await generate_stubs(
                mcp_url=_srv["url"], server_name=_srv["name"],
                servers_dir=SERVERS_DIR, verbose=True,
            )
        else:
            logger.info("[STEP 2] Stub '%s': %d tool già presenti", _srv["name"], len(_py_stubs))

    # ── STEP 3: create_agent (discovery, selection, codegen) ──────────────
    # llm_enabled=True serve al CodeGenerator (via litellm) per generate_from_prompt.
    # L'executor di default NON viene usato per l'esecuzione (usiamo _rest_execute).
    agent = create_agent(
        servers_dir=str(SERVERS_DIR.relative_to(_ROOT)),
        llm_enabled=True,
        llm_provider="azure_openai",
        llm_azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        llm_azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
        llm_api_key=os.environ["AZURE_OPENAI_API_KEY"],
    )
    logger.info("[STEP 3] Agent pronto (discovery+selection+codegen via framework)")

    # ── STEP 4: FilesystemHelper → ToolSelector ───────────────────────────
    # discover_tools/_select_tools_for_task sono sync ma chiamano asyncio.run()
    # internamente → vanno eseguiti in un thread separato per non bloccare il loop.
    import concurrent.futures
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        discovered = await loop.run_in_executor(
            pool, lambda: agent.discover_tools(verbose=False)
        )
        selected = await loop.run_in_executor(
            pool, lambda: agent.select_tools_for_task(PROMPT, discovered, verbose=False)
        )
    logger.info("[STEP 4] Tool selezionati: %s", selected)

    # Primo tool selezionato, con il server di appartenenza
    server_name_selected, tool_safe = next(
        ((srv, tools[0]) for srv, tools in selected.items() if tools),
        (SERVERS_CONFIG[0]["name"], "news_get"),
    )
    server_url_selected = _SERVERS_BY_NAME.get(
        server_name_selected, SERVERS_CONFIG[0]["url"]
    )
    stub_file = SERVERS_DIR / server_name_selected / f"{tool_safe}.py"
    stub_src  = stub_file.read_text(encoding="utf-8")

    # Recupera il nome originale MCP dallo stub (es. "news-get")
    m = re.search(r'call_mcp_tool\([^,]+,\s*"([^"]+)"', stub_src)
    original_tool = m.group(1) if m else tool_safe.replace("_", "-")

    # ── STEP 5: Campione reale (struttura risposta) ────────────────────────
    logger.info("[STEP 5] Chiamata campione: %s/%s({})", server_name_selected, original_tool)
    sample = await _mcp_call(original_tool, {}, server_url_selected)
    sample_json = json.dumps(sample, ensure_ascii=False, indent=2)[:3000]
    logger.info("[STEP 5] Campione ricevuto: %d chars", len(sample_json))

    # ── STEP 6: CodeGenerator → genera codice con struttura reale ─────────
    # Usa generate_from_prompt del framework (litellm → Azure OpenAI)
    logger.info("[STEP 6] Generazione codice via CodeGenerator (litellm) ...")
    code_raw = agent.code_generator.generate_from_prompt(
        system_content=(
            "Sei un generatore di codice Python. "
            "Rispondi SOLO con codice eseguibile, senza markdown, senza spiegazioni."
        ),
        user_content=(
            f"Importa la funzione con:\n"
            f"  from servers.{server_name_selected}.{tool_safe} import {tool_safe}\n\n"
            f"Firma della funzione:\n{stub_src}\n\n"
            f"Campione REALE della risposta (1 risultato):\n{sample_json}\n\n"
            f"Prompt utente: {PROMPT!r}\n\n"
            "Scrivi codice che:\n"
            f"1. Importa {tool_safe} come indicato sopra\n"
            "2. Chiama la funzione con limit=5 (se esiste), lang='it' se utile\n"
            "3. Naviga la struttura ESATTA della risposta come nel campione\n"
            "4. Stampa i risultati numerati, con titolo e testo\n\n"
            "Regole: non ridefinire la funzione; non reimportare json, re, urllib."
        ),
    )
    if not code_raw:
        logger.error("[STEP 6] CodeGenerator non ha prodotto codice (litellm disponibile?)")
        sys.exit(1)

    # Ripulisce fence markdown se presenti
    for pfx in ("```python\n", "```python", "```\n", "```"):
        if code_raw.startswith(pfx):
            code_raw = code_raw[len(pfx):]
            break
    if code_raw.endswith("```"):
        code_raw = code_raw[:-3]
    code = code_raw.strip()
    logger.info("[STEP 6] Codice generato (%d chars):\n%s", len(code), code)

    # ── STEP 7: Upload workspace + Esecuzione via execd REST (porta 44772) ──
    # 1. POST /directories — crea struttura directory nel container
    # 2. POST /files/upload — multipart upload di client/ e servers/<name>/
    # 3. POST /code — esegue solo il codice generato (no preambolo base64)
    logger.info("[STEP 7] Upload workspace via execd API (%s) ...", OPENSANDBOX_URL)
    all_server_names = [s["name"] for s in SERVERS_CONFIG]
    _upload_workspace(proxy_port, SANDBOX_HOST, SERVERS_DIR, all_server_names, OPENSANDBOX_URL)

    # Clear the Jupyter kernel's module cache for workspace packages so the
    # freshly uploaded files are always imported, not stale cached modules.
    sys_path_header = (
        "import sys\n"
        "for _k in list(sys.modules.keys()):\n"
        "    if _k.startswith(('client', 'servers')):\n"
        "        del sys.modules[_k]\n"
        "sys.path.insert(0, '/workspace')\n\n"
    )
    full_code = sys_path_header + code
    logger.debug("[STEP 7] Codice da eseguire (%d chars):\n%s", len(full_code), full_code[:500])
    logger.info("[STEP 7] Esecuzione codice via execd REST ...")
    stdout, stderr = _rest_execute(full_code, OPENSANDBOX_URL)

    if stderr:
        logger.error("[STEP 7] Stderr: %s", stderr)
    if stdout:
        first_line = stdout.splitlines()[0] if stdout.strip() else ""
        if len(first_line) > 120:
            first_line = first_line[:120] + "..."
        logger.info("[STEP 7] Output (prima riga): %s", first_line)
    elif not stderr:
        logger.warning("[STEP 7] Nessun output")

    proxy_srv.shutdown()
    logger.info("Demo completata.")


if __name__ == "__main__":
    asyncio.run(main())
