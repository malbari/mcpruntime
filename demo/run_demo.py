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

  2. Sample MCP call
     Chiama il tool scelto con argomenti vuoti per ottenere la struttura reale
     della risposta. Usata dal LLM come schema concreto per generare codice
     che naviga correttamente i campi (evita allucinazioni sulla struttura dati).

  3. Code generation (LLM)
     Il CodeGenerator produce codice Python personalizzato per il prompt,
     informato dalla firma dello stub e dalla risposta campione.

  4. Kernel reset
     DELETE /code/contexts — azzera lo stato Jupyter nel container prima di
     ogni esecuzione. Garantisce isolamento tra richieste successive e previene
     che moduli cachati da una richiesta precedente inquinino quella attuale.

  5. Esecuzione nel container
     POST /code — invia il codice generato a execd (NDJSON streaming).
     Il codice importa i tool da /workspace/servers/<server>/<tool>.py e
     chiama il proxy per le chiamate MCP reali.

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
SANDBOX_HOST    = os.environ.get("SANDBOX_HOST", "host.docker.internal")
OPENSANDBOX_URL = os.environ.get("OPENSANDBOX_URL", "http://localhost:44772")
PROMPT          = "Mi dici le ultime 5 news sul turismo?"
SERVERS_DIR     = _ROOT / "servers"

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
        try:
            p = json.loads(body)
            server_name = p.get("server", "")
            server_url  = self._servers.get(server_name)
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

    server_name, tool_safe = next(
        ((srv, tools[0]) for srv, tools in selected.items() if tools),
        (SERVERS_CONFIG[0]["name"], "news_get"),
    )
    server_url = state.servers_by_name.get(server_name, SERVERS_CONFIG[0]["url"])
    stub_file = SERVERS_DIR / server_name / f"{tool_safe}.py"
    stub_src = stub_file.read_text(encoding="utf-8")

    m = re.search(r'call_mcp_tool\([^,]+,\s*"([^"]+)"', stub_src)
    original_tool = m.group(1) if m else tool_safe.replace("_", "-")

    # ── 2. Sample MCP call ────────────────────────────────────────────────
    # Chiama il tool con args vuoti per ottenere la struttura reale della
    # risposta. Il LLM usa questo schema concreto per generare codice che
    # naviga i campi corretti (evita allucinazioni sulla struttura dati).
    logger.info("[Request] Sample call: %s/%s", server_name, original_tool)
    sample = await _mcp_call(original_tool, {}, server_url)
    sample_json = json.dumps(sample, ensure_ascii=False, indent=2)[:3000]
    logger.info("[Request] Campione ricevuto: %d chars", len(sample_json))

    # ── 3. Code generation (LLM) ──────────────────────────────────────────
    # Il CodeGenerator genera codice Python personalizzato per il prompt.
    # Input: firma dello stub + risposta campione + prompt utente.
    # Output: codice Python pronto per essere eseguito nel container.
    logger.info("[Request] Generazione codice via LLM ...")
    code_raw = state.agent.code_generator.generate_from_prompt(
        system_content=(
            "Sei un generatore di codice Python. "
            "Rispondi SOLO con codice eseguibile, senza markdown, senza spiegazioni."
        ),
        user_content=(
            f"Importa la funzione con:\n"
            f"  from servers.{server_name}.{tool_safe} import {tool_safe}\n\n"
            f"Firma della funzione:\n{stub_src}\n\n"
            f"Campione REALE della risposta (1 risultato):\n{sample_json}\n\n"
            f"Prompt utente: {prompt!r}\n\n"
            "Scrivi codice che:\n"
            f"1. Importa {tool_safe} come indicato sopra\n"
            "2. Chiama la funzione con limit=5 (se esiste), lang='it' se utile\n"
            "3. Naviga la struttura ESATTA della risposta come nel campione\n"
            "4. Stampa i risultati numerati, con titolo e testo\n\n"
            "Regole: non ridefinire la funzione; non reimportare json, re, urllib."
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
    logger.info("[Request] Codice generato (%d chars):\n%s", len(code), code)

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
    code_with_preamble = (
        "import sys\n"
        "for _k in list(sys.modules.keys()):\n"
        "    if _k.startswith(('client', 'servers')):\n"
        "        del sys.modules[_k]\n"
        "sys.path.insert(0, '/workspace')\n\n"
    ) + code

    logger.info("[Request] Esecuzione nel container (%s) ...", OPENSANDBOX_URL)
    stdout, stderr = _rest_execute(code_with_preamble, OPENSANDBOX_URL)

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

async def main() -> None:
    """Simula il ciclo di vita di un server: startup → handle_prompt → shutdown."""
    state = await startup()
    try:
        await handle_prompt(state, PROMPT)
    finally:
        state.proxy_srv.shutdown()
        logger.info("Demo completata.")


if __name__ == "__main__":
    asyncio.run(main())
