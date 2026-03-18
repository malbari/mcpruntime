"""
PTC Agent — Core dell'agente server-side per MCPRuntime
=======================================================

Modulo riutilizzabile che separa la logica dell'Agent PTC (startup, gestione
prompt, proxy MCP, upload workspace, esecuzione sandbox) dal codice demo/test.

Due fasi:
  - **startup()**  → ``AppState``  (una volta sola, risorse condivise)
  - **handle_prompt(state, prompt)** → ``str``  (per ogni richiesta utente)

Può essere importato da una demo batch, da un server web, o da una chat
conversazionale.  Tutte le risorse costose vengono allocate una sola volta
in ``startup`` e condivise (read-only) tra le richieste.
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

logger = logging.getLogger("ptc_agent")

# ── Percorsi resolti rispetto alla root del progetto ─────────────────────────
_AGENT_DIR = Path(__file__).parent.resolve()
_ROOT = _AGENT_DIR.parent
_PROMPTS_DIR = _AGENT_DIR / "prompts"

# ── Config ───────────────────────────────────────────────────────────────────
SANDBOX_HOST = os.environ.get("SANDBOX_HOST", "host.docker.internal")
OPENSANDBOX_URL = os.environ.get("OPENSANDBOX_URL", "http://localhost:44772")
SERVERS_DIR = _ROOT / "servers"


# ══════════════════════════════════════════════════════════════════════════════
#  Prompt template loader
# ══════════════════════════════════════════════════════════════════════════════

def _load_template(name: str) -> str:
    """Carica un template da demo/prompts/<name> e ne restituisce il testo."""
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _render(template: str, **kwargs: str) -> str:
    """Risolve i placeholder ``{{chiave}}`` nel template con i valori forniti."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{{" + key + "}}", value)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  1 — Proxy MCP  (container → host → server MCP)
# ══════════════════════════════════════════════════════════════════════════════

async def _mcp_call(tool: str, args: dict, url: str) -> Any:
    """Chiama un tool sul server MCP via fastmcp."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    async with Client(StreamableHttpTransport(url=url.rstrip("/") + "/")) as c:
        raw = await c.call_tool(tool, args)
    item = (raw[0] if isinstance(raw, list) and raw
            else getattr(raw, "content", [None])[0] if hasattr(raw, "content") and raw.content
            else raw)
    text = getattr(item, "text", None)
    try:
        return json.loads(text) if text else raw
    except (json.JSONDecodeError, TypeError):
        return text or raw


class _ProxyHandler(BaseHTTPRequestHandler):
    """Riceve POST /call-tool e /ask-llm dal container, instrada di conseguenza."""
    _servers: dict[str, str] = {}

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
            server_url = self._servers.get(server_name)
            if not server_url:
                raise ValueError(f"Server MCP sconosciuto: {server_name!r}")
            logger.info("[Sandbox → Proxy] call-tool: %s/%s(%s)",
                        server_name, p["tool"], json.dumps(p.get("args", {}))[:80])
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_mcp_call(p["tool"], p.get("args", {}), server_url))
            finally:
                loop.close()
            _preview = str(result)
            if len(_preview) > 200:
                _preview = _preview[:200] + "..."
            logger.info("[Proxy → Sandbox] MCP response: %s", _preview)
            resp = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        except Exception as exc:
            logger.error("[Proxy] Errore call-tool: %s", exc)
            err = json.dumps({"__mcp_error__": str(exc)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def _handle_ask_llm(self, body: bytes) -> None:
        """Sandbox-generated step: LLM #2 genera codice di display.

        Questo step può essere richiamato più volte dalla sandbox durante
        l'esecuzione di un singolo prompt (es. prima discovery schema, poi
        esecuzione SQL, poi generazione grafico).
        """
        try:
            import litellm
            p = json.loads(body)
            user_prompt = p.get("user_prompt", "")
            response_data = p.get("response_data", "")
            available_tools = p.get("available_tools", "[]")
            skills_context = p.get("skills_context", "")

            # Carica template da file
            sys_tpl = _load_template("sandbox_system.txt")
            usr_tpl = _load_template("sandbox_user.txt")

            sys_content = _render(sys_tpl,
                                  skills_context=(skills_context + "\n\n") if skills_context else "")
            usr_content = _render(usr_tpl,
                                  user_prompt=user_prompt,
                                  response_data=response_data,
                                  available_tools=available_tools)

            messages = [
                {"role": "system", "content": sys_content},
                {"role": "user", "content": usr_content},
            ]

            llm_resp = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/step-3.5-flash"),
                messages=messages,
                api_base=os.environ.get("LLM_API_BASE"),
                api_key=os.environ.get("LLM_API_KEY"),
                api_version=os.environ.get("LLM_API_VERSION") or None,
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
        logger.debug("[Proxy HTTP] %s", fmt % args)


def _start_proxy(servers_config: list[dict]) -> tuple[socketserver.TCPServer, int, dict[str, str]]:
    """Avvia il proxy e restituisce (server, porta, {name: url})."""
    servers_by_name = {s["name"]: s["url"] for s in servers_config}

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
# ══════════════════════════════════════════════════════════════════════════════

def _proxy_client_src(port: int, sandbox_host: str) -> str:
    """Sorgente Python di client/mcp_client.py proxy-aware da iniettare nel container."""
    return (
        '"""call_mcp_tool e ask_llm proxy-aware — iniettato da ptc_agent."""\n'
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
        "    skills_context: str = '',\n"
        ") -> str:\n"
        "    \"\"\"Chiama LLM #2 (sandbox-generated) tramite il proxy e restituisce codice Python.\n"
        "\n"
        "    Può essere richiamato più volte durante l'esecuzione di un singolo prompt.\n"
        "    \"\"\"\n"
        "    _url = f'http://{_SANDBOX_HOST}:{_PROXY_PORT}/ask-llm'\n"
        "    _body = json.dumps({\n"
        "        'user_prompt': user_prompt,\n"
        "        'response_data': response_data,\n"
        "        'available_tools': available_tools,\n"
        "        'skills_context': skills_context,\n"
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
    """Crea directory e uploada file nel container via execd API."""
    import httpx

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
        dirs_payload: dict[str, dict] = {
            "/workspace/client": {"mode": 755},
            "/workspace/servers": {"mode": 755},
        }
        for sn in server_names:
            dirs_payload[f"/workspace/servers/{sn}"] = {"mode": 755}
        resp = client.post(f"{base_url}/directories", json=dirs_payload)
        resp.raise_for_status()
        logger.debug("[Upload] Directory create: %s", list(dirs_payload))

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
    """Elimina tutti i contesti Python in execd (reset kernel)."""
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
    """Esegue POST /code e raccoglie stdout/stderr da NDJSON."""
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
    """Reset kernel, invia codice a execd, riprova una volta se busy."""
    _reset_kernel(base_url)
    stdout, stderr = _parse_ndjson(base_url, code)
    if stderr and stderr.startswith("RUNTIME_ERROR"):
        logger.warning("[execd] Kernel occupato, reset e nuovo tentativo ...")
        _reset_kernel(base_url)
        stdout, stderr = _parse_ndjson(base_url, code)
    return stdout, stderr


# ══════════════════════════════════════════════════════════════════════════════
#  AppState — stato condiviso tra le richieste (read-only dopo startup)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AppState:
    """Risorse inizializzate in startup(), condivise (read-only) per ogni richiesta."""
    proxy_srv: socketserver.TCPServer
    proxy_port: int
    servers_by_name: dict[str, str]
    agent: Any
    discovered_tools: dict
    all_server_names: list[str]
    skills_md: str
    skills_sections: dict[str, str]


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP  — una volta sola all'avvio del processo
# ══════════════════════════════════════════════════════════════════════════════

async def startup(servers_config: list[dict], skills_path: Optional[Path] = None) -> AppState:
    """Inizializza tutte le risorse condivise tra le richieste.

    Parameters
    ----------
    servers_config : list[dict]
        Lista server MCP (da servers.json).
    skills_path : Path | None
        Percorso al file SKILLS.md. Se None, non vengono caricate skill.
    """
    from mcpruntime import create_agent

    logger.info("=" * 60)
    logger.info("PTC Agent — Startup")
    logger.info("=" * 60)

    # ── 1. Genera stub (idempotente) ──────────────────────────────────────
    sys.path.insert(0, str(_ROOT / "scripts"))
    from generate_tool_files import generate_stubs  # type: ignore[import]
    for srv in servers_config:
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
    proxy_srv, proxy_port, servers_by_name = _start_proxy(servers_config)
    logger.info("[Startup 2/5] Proxy MCP su porta %d", proxy_port)

    # ── 3. Agent (embeddings + LLM client) ───────────────────────────────
    _llm_model = os.environ.get("LLM_MODEL", "openai/step-3.5-flash")
    _llm_api_key = os.environ.get("LLM_API_KEY", "")
    _llm_api_base = os.environ.get("LLM_API_BASE")

    # Deduce provider/model per create_agent dal formato litellm "provider/model"
    if "/" in _llm_model:
        _provider_prefix, _model_name = _llm_model.split("/", 1)
    else:
        _provider_prefix, _model_name = "openai", _llm_model

    _create_kwargs: dict[str, Any] = {
        "servers_dir": str(SERVERS_DIR.relative_to(_ROOT)),
        "llm_enabled": True,
        "llm_api_key": _llm_api_key,
        "llm_model": _model_name,
    }
    if _provider_prefix == "azure":
        _create_kwargs["llm_provider"] = "azure_openai"
        _create_kwargs["llm_azure_endpoint"] = _llm_api_base or ""
        _create_kwargs["llm_azure_deployment"] = _model_name
    else:
        _create_kwargs["llm_provider"] = _provider_prefix

    agent = create_agent(**_create_kwargs)

    # Per provider non-Azure, sovrascriviamo api_base/model direttamente
    # perché create_agent non ha un parametro generico api_base.
    if _provider_prefix != "azure" and _llm_api_base:
        agent.code_generator._api_base = _llm_api_base
        agent.code_generator._model_name = _llm_model  # litellm vuole "provider/model"
    # Applica threshold da env (sovrascrive i default del framework)
    _sim_th = os.environ.get("TOOL_SIMILARITY_THRESHOLD")
    if _sim_th is not None:
        agent.tool_selector.similarity_threshold = float(_sim_th)
    _top_k = os.environ.get("TOOL_TOP_K")
    if _top_k is not None:
        agent.tool_selector.top_k = int(_top_k)
    agent.tool_selector._get_model()
    logger.info(
        "[Startup 3/5] Agent pronto (model=%s, threshold=%.2f, top_k=%d)",
        _llm_model,
        agent.tool_selector.similarity_threshold,
        agent.tool_selector.top_k,
    )

    # ── 4. Tool discovery (cached) ────────────────────────────────────────
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        loop = asyncio.get_event_loop()
        discovered_tools = await loop.run_in_executor(
            pool, lambda: agent.discover_tools(verbose=False)
        )
    tool_count = sum(len(t) for t in discovered_tools.values())
    logger.info("[Startup 4/5] %d tool scoperti in %d server", tool_count, len(discovered_tools))

    # ── 4b. Applica whitelist/blacklist da servers.json ───────────────────
    _tool_filters: dict[str, dict] = {
        srv["name"]: srv
        for srv in servers_config
        if "tool_whitelist" in srv or "tool_blacklist" in srv
    }
    if _tool_filters:
        for srv_name, srv_cfg in _tool_filters.items():
            if srv_name not in discovered_tools:
                continue
            all_tools = list(discovered_tools[srv_name])
            whitelist = srv_cfg.get("tool_whitelist")
            blacklist = srv_cfg.get("tool_blacklist", [])
            if whitelist is not None:
                filtered = [t for t in all_tools if t in whitelist]
                removed = [t for t in all_tools if t not in whitelist]
                mode = "whitelist"
            else:
                filtered = [t for t in all_tools if t not in blacklist]
                removed = [t for t in all_tools if t in blacklist]
                mode = "blacklist"
            discovered_tools[srv_name] = filtered
            logger.info(
                "[Startup] Filtro %s '%s': %d tool visibili %s, %d rimossi %s",
                mode, srv_name, len(filtered), filtered, len(removed), removed,
            )

    # ── 5. Workspace upload ───────────────────────────────────────────────
    all_server_names = [s["name"] for s in servers_config]
    _upload_workspace(proxy_port, SANDBOX_HOST, SERVERS_DIR, all_server_names, OPENSANDBOX_URL)
    logger.info("[Startup 5/5] Workspace caricato nel container OpenSandbox")

    logger.info("=" * 60)
    logger.info("Startup completato — pronto a ricevere richieste")
    logger.info("=" * 60)

    # ── Carica SKILLS.md ──────────────────────────────────────────────────
    skills_md = ""
    if skills_path and skills_path.exists():
        skills_md = skills_path.read_text(encoding="utf-8")

    skills_sections: dict[str, str] = {}
    if skills_md:
        for _m in re.finditer(r'^## (\S+)\n(.*?)(?=^## |\Z)', skills_md, re.MULTILINE | re.DOTALL):
            skills_sections[_m.group(1)] = _m.group(2).strip()
        logger.info(
            "[Startup] SKILLS.md caricato: %d sezioni (%s) → entrano nel corpus hybrid search",
            len(skills_sections), ", ".join(skills_sections),
        )

    return AppState(
        proxy_srv=proxy_srv,
        proxy_port=proxy_port,
        servers_by_name=servers_by_name,
        agent=agent,
        discovered_tools=discovered_tools,
        all_server_names=all_server_names,
        skills_md=skills_md,
        skills_sections=skills_sections,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PER RICHIESTA  — handle_prompt
# ══════════════════════════════════════════════════════════════════════════════

async def handle_prompt(state: AppState, prompt: str) -> str:
    """Gestisce un singolo prompt utente e restituisce l'output del container.

    Fasi:
      1. Tool selection (hybrid search: BM25 + dense embeddings + skill anchors)
      2. Agent-generated step  — LLM #1: genera codice orchestratore
      3. Sandbox-generated step — LLM #2 (via proxy, può essere invocato N volte):
         genera codice display a partire dai dati reali ottenuti dal tool
    """
    # ── 1. Tool selection — Due corpora separati: tool e skill ───────────
    tool_descriptions = state.agent.tool_selector.get_tool_descriptions(
        state.agent.fs_helper, state.discovered_tools
    )

    _use_gpu = (
        getattr(state.agent.optimization_config, "enabled", True)
        and getattr(state.agent.optimization_config, "gpu_embeddings", True)
    )

    # Pass-1: hybrid search sui tool
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        loop = asyncio.get_event_loop()
        selected = await loop.run_in_executor(
            pool, lambda: state.agent.tool_selector.select_tools(
                prompt, tool_descriptions, use_gpu=_use_gpu
            )
        )
    _pass1_is_fallback = getattr(state.agent.tool_selector, "_last_was_fallback", False)

    # Pass-2: hybrid search sulle sezioni skill
    if state.skills_sections:
        _skill_descs: dict[tuple, str] = {
            (_srv, "__skill__"): f"{_srv}: {_text}"
            for _srv, _text in state.skills_sections.items()
            if _srv in state.discovered_tools
        }
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool2:
            _loop2 = asyncio.get_event_loop()
            _skill_result = await _loop2.run_in_executor(
                _pool2, lambda: state.agent.tool_selector.select_tools(
                    prompt, _skill_descs, use_gpu=_use_gpu
                )
            )
        _skill_anchored: set[str] = set(_skill_result.keys())
        for _srv in _skill_anchored:
            if (_srv not in selected or _pass1_is_fallback) and _srv in state.discovered_tools:
                _srv_descs = {k: v for k, v in tool_descriptions.items() if k[0] == _srv}
                if _srv_descs:
                    _skills_text = state.skills_sections.get(_srv, "")
                    _anchor_query = f"{prompt}\n{_skills_text}" if _skills_text else prompt
                    _srv_sel = state.agent.tool_selector.select_tools(
                        _anchor_query, _srv_descs, use_gpu=_use_gpu, threshold_override=0.0
                    )
                    _sel_tools = list(_srv_sel.get(_srv, []))
                else:
                    _sel_tools = []
                if not _sel_tools:
                    _sel_tools = list(state.discovered_tools[_srv])[:1]
                _cap = 3 if len(state.discovered_tools[_srv]) <= 5 else 2
                selected[_srv] = _sel_tools[:_cap]
                logger.info(
                    "[Request] Skill anchor: '%s' (hybrid) → stub selezionati: %s",
                    _srv, selected[_srv],
                )

        if _pass1_is_fallback and _skill_anchored:
            for _fallback_srv in list(selected.keys()):
                if _fallback_srv not in _skill_anchored:
                    logger.info(
                        "[Request] Pass-1 fallback '%s' rimosso: skill anchors più pertinenti disponibili",
                        _fallback_srv,
                    )
                    selected.pop(_fallback_srv)
    else:
        _skill_anchored = set()

    # Filtered skills per LLM
    _relevant_servers = set(selected.keys()) | _skill_anchored
    filtered_skills_md = "\n\n".join(
        f"## {s}\n{state.skills_sections[s]}"
        for s in _relevant_servers
        if s in state.skills_sections
    )
    if filtered_skills_md:
        logger.info(
            "[Request] Skill sections filtrate per LLM: %s",
            ", ".join(s for s in _relevant_servers if s in state.skills_sections),
        )

    logger.info("[Request] Tool selezionati: %s", selected)

    if not selected:
        logger.warning(
            "[Request] Nessun tool selezionato per il prompt — prompt ignorato."
        )
        return ""

    # ── 2. Raccogli stub dei tool candidati ──────────────────────────────
    _MAX_STUBS = 10
    candidate_stubs: list[dict] = []
    selected_tools_info: list[dict] = []

    _pass1_servers = [s for s in selected if s not in _skill_anchored]
    _anchor_servers = [s for s in selected if s in _skill_anchored]
    for _srv_order in _pass1_servers + _anchor_servers:
        if len(candidate_stubs) >= _MAX_STUBS:
            break
        for tname in selected.get(_srv_order, []):
            if len(candidate_stubs) >= _MAX_STUBS:
                break
            sf = SERVERS_DIR / _srv_order / f"{tname}.py"
            if not sf.exists():
                continue
            src = sf.read_text(encoding="utf-8")
            candidate_stubs.append({"server": _srv_order, "tool": tname, "stub_src": src})
            desc = ""
            for ln in src.splitlines():
                s_ln = ln.strip().strip('"')
                if s_ln and not s_ln.startswith("Stub per") and not s_ln.startswith("Generato"):
                    desc = s_ln[:200]
                    break
            selected_tools_info.append({"name": tname, "server": _srv_order, "description": desc})

    if not candidate_stubs:
        logger.error("[Request] Nessuno stub trovato per i tool selezionati — prompt ignorato.")
        return ""

    selected_tools_json = json.dumps(selected_tools_info, ensure_ascii=False)
    logger.info(
        "[Request] %d stub candidati, %d tool in available_tools",
        len(candidate_stubs), len(selected_tools_info),
    )

    all_stubs_src = "\n\n# ---\n\n".join(
        f"# Server: {c['server']}  Tool: {c['tool']}\n{c['stub_src']}"
        for c in candidate_stubs
    )

    # ── 3. Agent-generated step — LLM #1 genera codice orchestratore ─────
    logger.info("[Request] Agent-generated step: generazione codice orchestratore via LLM #1 ...")
    _skills_ctx = (filtered_skills_md + "\n\n") if filtered_skills_md else ""

    sys_tpl = _load_template("agent_system.txt")
    usr_tpl = _load_template("agent_user.txt")

    sys_content = _render(sys_tpl, skills_context=_skills_ctx)
    usr_content = _render(usr_tpl,
                          user_prompt=repr(prompt),
                          all_stubs_src=all_stubs_src)

    code_raw = state.agent.code_generator.generate_from_prompt(
        system_content=sys_content,
        user_content=usr_content,
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

    # ── Validazione hallucination: verifica che il tool importato esista ──
    _valid_tools = {c["tool"]: c["server"] for c in candidate_stubs}
    _import_m = re.search(r"^from\s+(\w+)\s+import\s+(\w+)", code, re.MULTILINE)
    if _import_m:
        _imported_mod = _import_m.group(1)
        _imported_fn = _import_m.group(2)
        if _imported_mod not in _valid_tools:
            _path_m = re.search(r"/workspace/servers/([^/'\"]+)", code)
            _target_srv = _path_m.group(1) if _path_m else None
            _correct_tool = next(
                (c["tool"] for c in candidate_stubs if _target_srv and c["server"] == _target_srv),
                candidate_stubs[0]["tool"] if candidate_stubs else None,
            )
            if _correct_tool:
                logger.warning(
                    "[Request] Hallucination rilevata: LLM ha usato '%s' invece di '%s' — correzione automatica",
                    _imported_mod, _correct_tool,
                )
                def _wb_replace(src: str, old: str, new: str) -> str:
                    return re.sub(r"\b" + re.escape(old) + r"\b", new, src)
                code = _wb_replace(code, _imported_mod, _correct_tool)
                if _imported_fn != _imported_mod:
                    code = _wb_replace(code, _imported_fn, _correct_tool)
                _imported_mod = _correct_tool
                _imported_fn = _correct_tool

        # ── Validazione parametri: rimuovi kwargs inventati da LLM ──────
        _stub_src = next(
            (c["stub_src"] for c in candidate_stubs if c["tool"] == _imported_mod), None
        )
        if _stub_src:
            _sig_m = re.search(
                r"def\s+" + re.escape(_imported_mod) + r"\s*\(([^)]*)\)",
                _stub_src,
            )
            if _sig_m:
                _sig_raw = _sig_m.group(1).strip()
                _valid_params: set[str] = set()
                for _p in _sig_raw.split(","):
                    _pname = _p.strip().split(":")[0].split("=")[0].strip().lstrip("*")
                    if _pname and _pname != "self":
                        _valid_params.add(_pname)
                _call_m = re.search(
                    r"\b" + re.escape(_imported_mod) + r"\s*\(([^)]*)\)",
                    code, re.DOTALL,
                )
                if _call_m:
                    _call_args = _call_m.group(1)
                    _used_kwargs = re.findall(r"\b(\w+)\s*=", _call_args)
                    _bad_kwargs = [k for k in _used_kwargs if k not in _valid_params]
                    if _bad_kwargs:
                        logger.warning(
                            "[Request] Parametri non validi per '%s': %s — rimozione automatica",
                            _imported_mod, _bad_kwargs,
                        )
                        _fixed_args = _call_args
                        for _bk in _bad_kwargs:
                            _fixed_args = re.sub(
                                r",?\s*\b" + re.escape(_bk) + r"\s*=[^,)]+", "", _fixed_args
                            )
                            _fixed_args = re.sub(
                                r"\b" + re.escape(_bk) + r"\s*=[^,)]+,?\s*", "", _fixed_args
                            )
                        _fixed_args = re.sub(r",\s*,", ",", _fixed_args).strip().strip(",").strip()
                        code = code[:_call_m.start(1)] + _fixed_args + code[_call_m.end(1):]

    _sep = "=" * 80
    logger.info("[Request] Codice generato (%d chars):\n%s\n%s\n%s", len(code), _sep, code, _sep)

    # ── 4+5. Kernel reset + esecuzione nel container ──────────────────────
    # Il codice orchestratore (agent-generated) viene eseguito nella sandbox.
    # Al suo interno chiama ask_llm() che invoca LLM #2 (sandbox-generated step),
    # potenzialmente più volte.
    _skills_json_escaped = json.dumps(filtered_skills_md, ensure_ascii=False)
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
        f"_mcp_mod._SANDBOX_HOST = {SANDBOX_HOST!r}\n"
        f"_available_tools_json = {selected_tools_json!r}\n"
        f"_skills_context = {_skills_json_escaped}\n\n"
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
        logger.debug("[Request] Output completo:\n%s", stdout.strip())
    else:
        logger.warning("[Request] Nessun output")

    return stdout or ""


def shutdown(state: AppState) -> None:
    """Rilascia le risorse dello state (proxy, ecc.)."""
    state.proxy_srv.shutdown()
    logger.info("PTC Agent — shutdown completato")
