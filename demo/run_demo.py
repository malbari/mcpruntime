#!/usr/bin/env python3
"""
MCPRuntime — Demo di integrazione server-side
=============================================

Mostra il pattern corretto per usare MCPRuntime in un servizio server-side
multi-utente. Il codice è organizzato in due fasi distinte con responsabilità
chiaramente separate.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STARTUP  (una volta sola, all'avvio del processo server)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Vedi: startup() → AppState

  1. Generazione stub
     Crea wrapper Python dai tool MCP (idempotente, salta se già presenti).
     Output: servers/<server>/<tool_name>.py

  2. Proxy MCP
     Avvia un bridge HTTP su porta libera: il codice eseguito nel container
     chiama http://host.docker.internal:<port>/call-tool e il proxy lo
     instrada al server MCP reale sull'host.
     Condiviso tra tutti gli utenti.

  3. Agent (create_agent)
     Inizializza FilesystemHelper, ToolSelector (carica il modello embeddings
     all-MiniLM-L6-v2 su MPS/CPU), CodeGenerator (LLM client via litellm).
     Costoso: caricamento modello ~4s, allocato una sola volta.

  4. Tool discovery
     Legge gli stub da disco e costruisce il catalogo di tool disponibili.
     Risultato cachato in AppState.discovered_tools, condiviso tra richieste.

  5. Workspace upload
     Carica stub e client proxy nel container OpenSandbox via:
       POST /directories  — mkdir -p delle directory necessarie
       POST /files/upload — multipart upload (un'unica richiesta per tutti i file)
     I file persistono sul filesystem del container finché è in esecuzione:
     non vanno ricaricati per ogni richiesta.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PER RICHIESTA  (per ogni prompt utente)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Vedi: handle_prompt(state, prompt) → str

  1. Tool selection
     Ricerca semantica (embeddings) sul catalogo cachato per trovare il tool
     più rilevante per il prompt dell'utente.

  2. Build tool info
     Raccoglie la lista dei tool selezionati (nome, server, descrizione) per
     passarla a LLM #2 come elenco di tool disponibili nel container.

  3. Code generation — LLM #1  (orchestratore)
     Il CodeGenerator produce codice orchestratore con schema fisso:
       a. Chiama il tool MCP principale → risposta reale a runtime
       b. Chiama ask_llm() via proxy → LLM #2 vede i dati reali + tool
       c. exec() il codice restituito da LLM #2 nel kernel del container
     LLM #1 deve solo dedurre i parametri corretti della chiamata al tool.

  4. Kernel reset
     DELETE /code/contexts — azzera lo stato Jupyter nel container prima di
     ogni esecuzione. Garantisce isolamento tra richieste successive e previene
     che moduli cachati da una richiesta precedente inquinino quella attuale.

  5. Esecuzione nel container  (flusso in due stadi)
     POST /code — invia il codice orchestratore a execd (NDJSON streaming).
     All'interno del container:
       • Il codice chiama il tool MCP via proxy /call-tool → dati reali
       • Chiama ask_llm() via proxy /ask-llm → LLM #2 genera display code
       • exec(display_code, globals()) → stampa l'output formattato
     Il campione MCP non viene più prelevato dall'host: LLM #2 vede i dati
     reali a runtime, eliminando un roundtrip host↔MCP per ogni richiesta.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  NOTE PER AMBIENTI MULTI-UTENTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • AppState è read-only dopo startup: handle_prompt è thread-safe per lettura.

  • Il proxy MCP è condiviso (socketserver.TCPServer gestisce connessioni
    concorrenti su thread separati).

  • Il kernel reset (DELETE /code/contexts) è GLOBALE: in produzione multi-utente
    usare contesti separati per utente:
      POST  /code/context          → {"language":"python"} → {"id": "<ctx_id>"}
      POST  /code  + body.context_id = ctx_id   → esecuzione isolata
      DELETE /code/contexts/<ctx_id>             → cleanup after request
    Ogni utente ha così il suo kernel indipendente senza interferenze.

  • Per isolamento hardware completo, usare un container OpenSandbox per utente
    (sandbox pool) anziché un container condiviso.

Prerequisiti (gestiti da run_demo.sh):
  - Virtual env con: fastmcp httpx litellm python-dotenv sentence-transformers
  - OpenSandbox execd porta 44772 accessibile
  - demo/servers.json configurato con i server MCP
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import socketserver
import sys
import threading
import urllib.request
from dataclasses import dataclass, field
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
SANDBOX_HOST       = os.environ.get("SANDBOX_HOST", "host.docker.internal")
OPENSANDBOX_URL    = os.environ.get("OPENSANDBOX_URL", "http://localhost:44772")
TEST_PROMPTS_FILE  = _DEMO_DIR / "test-prompts.txt"
SERVERS_DIR        = _ROOT / "servers"

# Lista server MCP — caricata da demo/servers.json (unico punto di configurazione)
_SERVERS_FILE   = _DEMO_DIR / "servers.json"
SERVERS_CONFIG: list[dict] = json.loads(_SERVERS_FILE.read_text(encoding="utf-8"))["servers"]


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
    """Riceve POST /call-tool dal container, chiama MCP, risponde JSON.

    La sottoclasse _Handler (creata in _start_proxy) inietta _servers come
    attributo di classe, così ogni istanza ha accesso al routing senza
    dipendenze da variabili globali di modulo.
    """
    _servers: dict[str, str] = {}  # sovrascritto da _Handler in _start_proxy

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/call-tool":
            self._handle_call_tool(body)
        elif self.path == "/ask-llm":
            self._handle_ask_llm(body)
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_call_tool(self, body: bytes) -> None:
        try:
            p = json.loads(body)
            server_name = p.get("server", "")
            server_url  = self._servers.get(server_name)
            if not server_url:
                raise ValueError(f"Server MCP sconosciuto: {server_name!r}")
            logger.info(f"[Sandbox → Proxy] call-tool: {server_name}/{p['tool']}({json.dumps(p.get('args',{}))[:80]})")
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_mcp_call(p["tool"], p.get("args", {}), server_url))
            finally:
                loop.close()
            _preview = str(result)
            if len(_preview) > 200:
                _preview = _preview[:200] + "..."
            logger.info(f"[Proxy → Sandbox] MCP response: {_preview}")
            resp = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        except Exception as exc:
            logger.error(f"[Proxy] Errore call-tool: {exc}")
            # Restituisce 200 con campo "__mcp_error__" — così il container può
            # leggere il messaggio invece di ricevere un HTTPError non gestibile.
            err = json.dumps({"__mcp_error__": str(exc)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def _handle_ask_llm(self, body: bytes) -> None:
        """Riceve {user_prompt, response_data, available_tools} dal container,
        chiama LLM #2 per generare codice di display e risponde {code: str}."""
        try:
            import litellm
            p = json.loads(body)
            user_prompt     = p.get("user_prompt", "")
            response_data   = p.get("response_data", "")
            available_tools = p.get("available_tools", "[]")

            messages = [
                {
                    "role": "system",
                    "content": (
                        "Sei un generatore di codice Python. "
                        "Rispondi SOLO con codice eseguibile, senza markdown, senza spiegazioni."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Prompt utente originale: {user_prompt}\n\n"
                        f"Dati ottenuti dal tool MCP "
                        f"(variabile `response` già in scope come dict Python):\n"
                        f"{response_data}\n\n"
                        f"Tool MCP disponibili (puoi chiamarne altri se necessario):\n"
                        f"{available_tools}\n\n"
                        "Per chiamare un tool aggiuntivo:\n"
                        "    from client.mcp_client import call_mcp_tool\n"
                        "    result = call_mcp_tool(server_name, tool_name, {'param': value})\n\n"
                        "Scrivi codice Python che:\n"
                        "1. Usa `response` (già in scope) per estrarre i dati\n"
                        "2. Stampa i risultati in modo leggibile, rispondendo al prompt\n"
                        "   NOTA: rispetta l'ordine dei dati restituito dal server MCP, "
                        "NON aggiungere ordinamenti (es. sorted()) arbitrari.\n"
                        "3. Chiama altri tool (dall'elenco) solo se necessario\n"
                        "Regole: non ridefinire `response`; json è già importato."
                    ),
                },
            ]

            llm_resp = litellm.completion(
                model=f"azure/{os.environ.get('AZURE_OPENAI_DEPLOYMENT', 'gpt-4.1')}",
                messages=messages,
                api_base=os.environ.get("AZURE_OPENAI_ENDPOINT"),
                api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
                max_tokens=2048,
            )
            code_raw = llm_resp.choices[0].message.content or ""
            # Strip markdown fences if present
            for pfx in ("```python\n", "```python", "```\n", "```"):
                if code_raw.startswith(pfx):
                    code_raw = code_raw[len(pfx):]
                    break
            if code_raw.endswith("```"):
                code_raw = code_raw[:-3]
            code = code_raw.strip()
            _sep = "=" * 80
            logger.info(
                "[Proxy → Sandbox] LLM #2 codice generato (%d chars) — verrà exec() in sandbox:\n%s\n%s\n%s",
                len(code), _sep, code, _sep,
            )

            resp = json.dumps({"code": code}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        except Exception as exc:
            logger.error("[Proxy] Errore ask-llm: %s", exc)
            err = json.dumps({"error": str(exc), "code": ""}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def log_message(self, fmt, *args):
        logger.debug(f"[Proxy HTTP] {fmt % args}")


def _start_proxy(servers_config: list[dict]) -> tuple[socketserver.TCPServer, int, dict[str, str]]:
    """Avvia il proxy e restituisce (server, porta, {name: url})."""
    servers_by_name = {s["name"]: s["url"] for s in servers_config}

    # Il ProxyHandler accede a servers_by_name tramite closure sulla classe
    class _Handler(_ProxyHandler):
        _servers = servers_by_name

    srv = socketserver.TCPServer(("", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for name, url in servers_by_name.items():
        logger.debug("[Proxy] %s → %s", name, url)
    return srv, port, servers_by_name


# ══════════════════════════════════════════════════════════════════════════════
#  2 — Upload workspace nel container via execd API
#      POST /directories  — crea le directory (mkdir -p)
#      POST /files/upload — multipart: metadata (JSON file-part) + file (binary)
# ══════════════════════════════════════════════════════════════════════════════

def _proxy_client_src(port: int, sandbox_host: str) -> str:
    """Sorgente Python di client/mcp_client.py proxy-aware da iniettare nel container."""
    return (
        '"""call_mcp_tool e ask_llm proxy-aware — iniettato da demo."""\n'
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
        "        _result = json.loads(_r.read())\n"
        "    if isinstance(_result, dict) and '__mcp_error__' in _result:\n"
        "        raise RuntimeError(f\"MCP error: {_result['__mcp_error__']}\")\n"
        "    return _result\n"
        "\n"
        "def ask_llm(\n"
        "    user_prompt: str,\n"
        "    response_data: str,\n"
        "    available_tools: str = '[]',\n"
        ") -> str:\n"
        "    \"\"\"Chiama LLM #2 tramite il proxy dell'host e restituisce codice Python eseguibile.\"\"\"\n"
        "    _url = f'http://{_SANDBOX_HOST}:{_PROXY_PORT}/ask-llm'\n"
        "    _body = json.dumps({\n"
        "        'user_prompt': user_prompt,\n"
        "        'response_data': response_data,\n"
        "        'available_tools': available_tools,\n"
        "    }).encode()\n"
        "    _req = urllib.request.Request(\n"
        "        _url, data=_body,\n"
        "        headers={'Content-Type': 'application/json'},\n"
        "        method='POST',\n"
        "    )\n"
        "    with urllib.request.urlopen(_req, timeout=60) as _r:\n"
        "        return json.loads(_r.read()).get('code', '')\n"
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
#  Stato globale del server  (inizializzato una volta sola in startup)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AppState:
    """Tutto ciò che viene creato allo startup e condiviso tra le richieste.

    Tutti i campi sono read-only dopo startup() → handle_prompt è thread-safe.
    """
    proxy_srv: socketserver.TCPServer       # proxy MCP (bridge container→host)
    proxy_port: int                          # porta assegnata dal SO
    servers_by_name: dict[str, str]          # name → URL server MCP
    agent: Any                               # agente MCPRuntime (model + LLM)
    discovered_tools: dict                   # catalogo tool (cachato da disco)
    all_server_names: list[str]              # nomi dei server da servers.json


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP  — eseguita una volta sola all'avvio del processo server
# ══════════════════════════════════════════════════════════════════════════════

async def startup() -> AppState:
    """Inizializza tutte le risorse condivise tra le richieste.

    Costoso (~5-10s): caricamento modello embeddings, LLM client, upload
    workspace nel container. Va chiamato una volta sola al boot del server.
    """
    from mcpruntime import create_agent

    logger.info("=" * 60)
    logger.info("MCPRuntime — Startup")
    logger.info("=" * 60)

    # ── 1. Genera stub (idempotente) ──────────────────────────────────────
    # I wrapper Python dai tool MCP vengono generati una volta e salvati su
    # disco in servers/<server>/<tool>.py. Operazione idempotente: salta i
    # server che hanno già gli stub.
    sys.path.insert(0, str(_ROOT / "scripts"))
    from generate_tool_files import generate_stubs  # type: ignore[import]
    for srv in SERVERS_CONFIG:
        stub_dir = SERVERS_DIR / srv["name"]
        existing = (
            [f for f in stub_dir.glob("*.py") if f.name != "__init__.py"]
            if stub_dir.exists() else []
        )
        if not existing:
            logger.info("[Startup 1/5] Generazione stub '%s' da %s ...", srv["name"], srv["url"])
            await generate_stubs(
                mcp_url=srv["url"], server_name=srv["name"],
                servers_dir=SERVERS_DIR, verbose=True,
            )
        else:
            logger.info("[Startup 1/5] Stub '%s': %d tool presenti", srv["name"], len(existing))

    # ── 2. Avvia proxy MCP ────────────────────────────────────────────────
    # Il proxy è un HTTP server locale (porta scelta dal SO) che il codice
    # nel container chiama per eseguire tool MCP. È condiviso tra tutte le
    # richieste e gestisce connessioni concorrenti su thread separati.
    proxy_srv, proxy_port, servers_by_name = _start_proxy(SERVERS_CONFIG)
    logger.info("[Startup 2/5] Proxy MCP su porta %d", proxy_port)

    # ── 3. Agent (embeddings + LLM client) ───────────────────────────────
    # create_agent carica il modello sentence-transformers (~4s su CPU,
    # meno su MPS) e inizializza il client LLM. Allocato una sola volta.
    agent = create_agent(
        servers_dir=str(SERVERS_DIR.relative_to(_ROOT)),
        llm_enabled=True,
        llm_provider="azure_openai",
        llm_azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        llm_azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
        llm_api_key=os.environ["AZURE_OPENAI_API_KEY"],
    )
    logger.info("[Startup 3/5] Agent pronto (embeddings + LLM client)")

    # ── 4. Tool discovery (cached) ────────────────────────────────────────
    # Legge gli stub da disco e costruisce il catalogo dei tool disponibili.
    # Il risultato viene salvato in AppState.discovered_tools e riusato per
    # ogni richiesta senza rileggere il filesystem.
    # NOTA: discover_tools chiama asyncio.run() internamente → thread separato.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        loop = asyncio.get_event_loop()
        discovered_tools = await loop.run_in_executor(
            pool, lambda: agent.discover_tools(verbose=False)
        )
    tool_count = sum(len(t) for t in discovered_tools.values())
    logger.info("[Startup 4/5] %d tool scoperti in %d server", tool_count, len(discovered_tools))

    # ── 5. Workspace upload (una sola volta) ──────────────────────────────
    # Carica stub e client proxy nel container OpenSandbox.
    # I file restano su disco del container finché è in esecuzione: non serve
    # ricaricarli per ogni richiesta. Solo mcp_client.py dipende dal proxy_port
    # (fisso dopo lo startup) → tutto stabile per tutta la vita del server.
    all_server_names = [s["name"] for s in SERVERS_CONFIG]
    _upload_workspace(proxy_port, SANDBOX_HOST, SERVERS_DIR, all_server_names, OPENSANDBOX_URL)
    logger.info("[Startup 5/5] Workspace caricato nel container OpenSandbox")

    logger.info("=" * 60)
    logger.info("Startup completato — pronto a ricevere richieste")
    logger.info("=" * 60)

    return AppState(
        proxy_srv=proxy_srv,
        proxy_port=proxy_port,
        servers_by_name=servers_by_name,
        agent=agent,
        discovered_tools=discovered_tools,
        all_server_names=all_server_names,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PER RICHIESTA  — eseguita per ogni prompt utente
# ══════════════════════════════════════════════════════════════════════════════

async def handle_prompt(state: AppState, prompt: str) -> str:
    """Gestisce un singolo prompt utente e restituisce l'output del container.

    Tutte le risorse costose (model, LLM client, stub su disco, proxy) sono
    già pronte in `state`. Questa funzione esegue solo le operazioni
    dipendenti dal prompt specifico.

    Multi-utente: in produzione sostituire il kernel reset globale con
    contesti per-utente (vedi note nel docstring del modulo).
    """
    # ── 1. Tool selection ─────────────────────────────────────────────────
    # Ricerca semantica sul catalogo cachato: trova il tool più pertinente
    # al prompt. Usa embeddings (MPS/CPU) senza rileggere disco o rete.
    # NOTA: select_tools_for_task chiama asyncio.run() → thread separato.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        loop = asyncio.get_event_loop()
        selected = await loop.run_in_executor(
            pool, lambda: state.agent.select_tools_for_task(
                prompt, state.discovered_tools, verbose=False
            )
        )
    logger.info("[Request] Tool selezionati: %s", selected)

    if not selected:
        logger.warning(
            "[Request] Nessun tool selezionato per il prompt (similarity sotto soglia) — "
            "prompt ignorato. Verifica le descrizioni dei tool o il modello embeddings."
        )
        return

    # ── 2. Raccogli stub di tutti i tool candidati ────────────────────────
    # La similarity search (top-k) filtra il catalogo a pochi candidati.
    # LLM #1 (GPT-4.1) sceglie autonomamente quale chiamare: è più preciso
    # di un ranking embedding per prompt in italiano con stub poco descrittivi.
    candidate_stubs: list[dict] = []   # [{server, tool, stub_src}]
    selected_tools_info: list[dict] = []

    for srv, tool_list in selected.items():
        for tname in tool_list:
            sf = SERVERS_DIR / srv / f"{tname}.py"
            if not sf.exists():
                continue
            src = sf.read_text(encoding="utf-8")
            candidate_stubs.append({"server": srv, "tool": tname, "stub_src": src})
            # Estrai prima riga descrittiva per LLM #2
            desc = ""
            for ln in src.splitlines():
                s = ln.strip().strip('"')
                if s and not s.startswith("Stub per") and not s.startswith("Generato"):
                    desc = s[:200]
                    break
            selected_tools_info.append({"name": tname, "server": srv, "description": desc})

    if not candidate_stubs:
        logger.error("[Request] Nessuno stub trovato per i tool selezionati — prompt ignorato.")
        return

    selected_tools_json = json.dumps(selected_tools_info, ensure_ascii=False)
    logger.info("[Request] Tool info per LLM #2: %s", selected_tools_json[:200])

    # Stubs concatenati per LLM #1
    all_stubs_src = "\n\n# ---\n\n".join(
        f"# Server: {c['server']}  Tool: {c['tool']}\n{c['stub_src']}"
        for c in candidate_stubs
    )

    # ── 3. Code generation — LLM #1 sceglie il tool e genera il codice ────
    # LLM #1 riceve TUTTI gli stub candidati e il prompt utente.
    # Sceglie autonomamente il tool più adatto, costruisce la chiamata,
    # e produce il codice orchestratore con schema fisso.
    logger.info("[Request] Generazione codice orchestratore via LLM #1 ...")
    code_raw = state.agent.code_generator.generate_from_prompt(
        system_content=(
            "Sei un generatore di codice Python. "
            "Rispondi SOLO con codice eseguibile, senza markdown, senza spiegazioni."
        ),
        user_content=(
            f"Prompt utente: {prompt!r}\n\n"
            f"Tool MCP candidati (stub Python già disponibili in /workspace/servers/):\n\n"
            f"{all_stubs_src}\n\n"
            "Scrivi ESATTAMENTE questo schema di codice.\n"
            "Scegli il tool PIÙ ADATTO al prompt tra quelli elencati.\n"
            "Sostituisci CHOSEN_SERVER con il nome del server scelto,\n"
            "CHOSEN_TOOL con il nome del tool scelto, e\n"
            "PLACEHOLDER_CALL con la chiamata corretta.\n"
            "\n"
            "import json, sys as _sys\n"
            "if '/workspace/servers/CHOSEN_SERVER' not in _sys.path: _sys.path.insert(0, '/workspace/servers/CHOSEN_SERVER')\n"
            "from CHOSEN_TOOL import CHOSEN_TOOL\n"
            "from client.mcp_client import ask_llm\n"
            "\n"
            "response = PLACEHOLDER_CALL\n"
            "\n"
            "display_code = ask_llm(\n"
            f"    user_prompt={prompt!r},\n"
            "    response_data=json.dumps(response, ensure_ascii=False)[:4000],\n"
            f"    available_tools={selected_tools_json!r},\n"
            ")\n"
            "\n"
            "exec(display_code, globals())\n"
            "\n"
            "Regole:\n"
            "- Scegli il tool più pertinente al prompt utente\n"
            "- Passa lang='it' se il parametro esiste nella firma\n"
            "- Passa limit=5 se il parametro esiste nella firma\n"
            "- NON inventare valori per parametri filtro (theme, category, type ecc.): lasciali None\n"
            "- Non modificare nessun'altra riga\n"
            "- Non aggiungere altro codice\n"
            "- Non reimportare json, urllib, re"
        ),
    )
    if not code_raw:
        raise RuntimeError("LLM non ha prodotto codice")

    for pfx in ("```python\n", "```python", "```\n", "```"):
        if code_raw.startswith(pfx):
            code_raw = code_raw[len(pfx):]
            break
    if code_raw.endswith("```"):
        code_raw = code_raw[:-3]
    code = code_raw.strip()
    _sep = "=" * 80
    logger.info("[Request] Codice generato (%d chars):\n%s\n%s\n%s", len(code), _sep, code, _sep)

    # ── 4+5. Kernel reset + esecuzione nel container ──────────────────────
    # Reset: DELETE /code/contexts — azzera lo stato Python nel container.
    # Garantisce che moduli cachati da richieste precedenti non inquinino
    # questa esecuzione. I FILE sul disco del container restano intatti.
    #
    # Il preamble sys.path è necessario per trovare /workspace dopo il reset.
    # La pulizia sys.modules rimuove eventuali import residui in memoria.
    #
    # MULTI-UTENTE: sostituire _rest_execute con esecuzione su contesto
    # dedicato per utente (context_id = hash(user_id)) per isolamento reale.
    # Il preamble:
    # 1. Pulisce TUTTI i moduli caricati da /workspace (inclusi stub con nomi
    #    corti come 'events_get' che il kernel Jupyter mantiene tra esecuzioni)
    # 2. Assicura /workspace nel path
    # 3. Importa mcp_client e INIETTA la porta corretta di QUESTO run
    code_with_preamble = (
        "import sys\n"
        "_del = [_k for _k in sys.modules\n"
        "        if hasattr(sys.modules[_k], '__file__')\n"
        "        and (sys.modules[_k].__file__ or '')\n"
        "        and '/workspace' in (sys.modules[_k].__file__ or '')]\n"
        "for _k in _del: del sys.modules[_k]\n"
        "for _k in [_k for _k in sys.modules if _k.startswith(('client', 'servers'))]:\n"
        "    del sys.modules[_k]\n"
        "if '/workspace' not in sys.path: sys.path.insert(0, '/workspace')\n"
        "import client.mcp_client as _mcp_mod\n"
        f"_mcp_mod._PROXY_PORT = {state.proxy_port}\n"
        f"_mcp_mod._SANDBOX_HOST = {SANDBOX_HOST!r}\n\n"
    ) + code

    logger.info("[Sandbox ▶ ENTER] Codice orchestratore → execd (%s)", OPENSANDBOX_URL)
    stdout, stderr = _rest_execute(code_with_preamble, OPENSANDBOX_URL)
    logger.info("[Sandbox ◀ EXIT]  Esecuzione completata")

    if stderr:
        logger.error("[Request] Stderr: %s", stderr)
    if stdout:
        first_line = stdout.splitlines()[0] if stdout.strip() else ""
        if len(first_line) > 120:
            first_line = first_line[:120] + "..."
        logger.info("[Request] Output (prima riga): %s", first_line)
    else:
        logger.warning("[Request] Nessun output")

    return stdout or ""


# ══════════════════════════════════════════════════════════════════════════════
#  Entrypoint demo  (simula un server che riceve una richiesta)
# ══════════════════════════════════════════════════════════════════════════════

def _load_prompts() -> list[str]:
    """Legge test-prompts.txt e restituisce le righe attive (ignora vuote e commenti)."""
    lines = TEST_PROMPTS_FILE.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


async def main() -> None:
    """Cicla su tutti i prompt in test-prompts.txt, separando ogni test con un divisore."""
    prompts = _load_prompts()
    if not prompts:
        logger.warning("Nessun prompt trovato in %s — esco.", TEST_PROMPTS_FILE)
        return

    SEP = "=" * 120

    state = await startup()
    try:
        for idx, prompt in enumerate(prompts, start=1):
            logger.info(SEP)
            logger.info("TEST %d/%d: %s", idx, len(prompts), prompt)
            logger.info(SEP)
            await handle_prompt(state, prompt)
            logger.info("Fine TEST %d/%d", idx, len(prompts))
    finally:
        state.proxy_srv.shutdown()
        logger.info(SEP)
        logger.info("Demo completata — %d prompt eseguiti.", len(prompts))
        logger.info(SEP)


if __name__ == "__main__":
    asyncio.run(main())
