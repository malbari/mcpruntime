#!/usr/bin/env bash
# =============================================================================
#  run_demo.sh
#  Setup virtual env e avvio demo (create_agent + OpenSandbox SDK)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
ENV_FILE="$SCRIPT_DIR/.env"

# ── Colori ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

echo -e "\n${BOLD}==================================================${NC}"
echo -e "${BOLD}  Demo — MCPRuntime con OpenSandbox SDK${NC}"
echo -e "${BOLD}==================================================${NC}\n"

# ── 1. Python ─────────────────────────────────────────────────────────────
PYTHON="$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)"
[[ -z "$PYTHON" ]] && err "Python non trovato. Installa Python 3.11+."

PYVER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
info "Python rilevato: $("$PYTHON" --version 2>&1) (path: $PYTHON)"

# Versione minima 3.11
PYMAJ="$(echo "$PYVER" | cut -d. -f1)"
PYMIN="$(echo "$PYVER" | cut -d. -f2)"
if (( PYMAJ < 3 || (PYMAJ == 3 && PYMIN < 11) )); then
    err "Python 3.11+ richiesto. Trovato: $PYVER"
fi
ok "Python $PYVER compatibile"

# ── 2. Virtual env ────────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creazione virtual env in $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual env creato"
else
    info "Virtual env già presente: $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
ok "Virtual env attivato: $(python --version 2>&1)"

# ── 3. Dipendenze ─────────────────────────────────────────────────────────
DEPS=(
    "fastmcp>=2.0"          # client MCP (StreamableHttpTransport)
    "openai>=1.0"           # AzureOpenAI (fallback diretto, non usato in demo ma utile)
    "python-dotenv"         # carica .env
    "httpx"                 # dipendenza fastmcp
    "litellm"               # usato da CodeGenerator.generate_from_prompt()
    "opensandbox"           # SDK per write_files() e run() nel container
    "sentence-transformers" # tool selector semantico (opzionale ma consigliato)
)

info "Installazione dipendenze nel venv ..."
pip install -q --upgrade pip
for dep in "${DEPS[@]}"; do
    if pip install -q "$dep"; then
        ok "Installato: $dep"
    else
        warn "Errore installando $dep — continuo (potrebbe già essere disponibile)"
    fi
done

# Verifica import critici
python -c "import fastmcp"         || err "fastmcp non importabile dopo installazione"
python -c "import openai"          || err "openai non importabile dopo installazione"
python -c "import litellm"         || err "litellm non importabile dopo installazione"
python -c "import opensandbox"     || err "opensandbox non importabile dopo installazione"
ok "Tutti i pacchetti verificati"

# ── 4. File .env ─────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    warn ".env non trovato in $SCRIPT_DIR"
    echo ""
    echo "  Crea il file $ENV_FILE con almeno:"
    echo "    AZURE_OPENAI_API_KEY=..."
    echo "    AZURE_OPENAI_ENDPOINT=https://<risorsa>.openai.azure.com"
    echo "    AZURE_OPENAI_DEPLOYMENT=gpt-4.1"
    echo ""
    echo "  URL dei server MCP: configura demo/servers.json"
    echo ""
    err "File .env mancante. Crealo e riprova."
fi

# Controlla variabili obbligatorie
source "$ENV_FILE"
[[ -z "${AZURE_OPENAI_API_KEY:-}" ]]   && err "AZURE_OPENAI_API_KEY non impostata in .env"
[[ -z "${AZURE_OPENAI_ENDPOINT:-}" ]]  && err "AZURE_OPENAI_ENDPOINT non impostata in .env"
SANDBOX_HOST_VAL="${SANDBOX_HOST:-host.docker.internal}"
if [[ "$SANDBOX_HOST_VAL" == "host.docker.internal" ]]; then
    warn "SANDBOX_HOST non impostato — usando 'host.docker.internal' (Docker Desktop Mac/Win)"
    warn "Su Linux imposta SANDBOX_HOST=172.17.0.1 (o l'IP del bridge Docker) nel .env"
else
    info "SANDBOX_HOST: $SANDBOX_HOST_VAL"
fi
ok ".env caricato e variabili obbligatorie presenti"

# ── 5. Stub server MCP (da demo/servers.json) ────────────────────────────
info "Controllo stub da demo/servers.json ..."
export PROJECT_ROOT
python - << 'PYEOF'
import asyncio, json, os, sys
from pathlib import Path
ROOT = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
servers_json = json.loads((ROOT / "demo" / "servers.json").read_text())
from generate_tool_files import generate_stubs  # type: ignore[import]
async def main():
    servers_dir = ROOT / "servers"
    for srv in servers_json["servers"]:
        stub_dir = servers_dir / srv["name"]
        stubs = (
            [f for f in stub_dir.glob("*.py") if f.name != "__init__.py"]
            if stub_dir.exists() else []
        )
        if stubs:
            print(f"  {srv['name']}: {len(stubs)} stub già presenti")
        else:
            print(f"  {srv['name']}: generazione stub da {srv['url']} ...")
            await generate_stubs(
                mcp_url=srv["url"], server_name=srv["name"],
                servers_dir=servers_dir, verbose=True,
            )
            print(f"  {srv['name']}: stub generati OK")
asyncio.run(main())
PYEOF
ok "Stub aggiornati"

# ── 6. OpenSandbox execd (porta 44772) ───────────────────────────────────
info "Verifica OpenSandbox execd REST API (porta 44772) ..."
if ! curl -sf -m 3 -X POST http://127.0.0.1:44772/code \
       -H 'Content-Type: application/json' \
       -d '{"context":{"language":"python"},"code":"print(1)"}' > /dev/null 2>&1; then
    echo ""
    err "OpenSandbox execd NON raggiungibile su porta 44772.
    Avvia il container:
      cd /Users/M.Albari/projects/opensandbox-python && docker compose up -d"
fi
ok "OpenSandbox execd attivo su :44772"

# ── 7. Server MCP (da demo/servers.json) ─────────────────────────────
info "Verifica server MCP da demo/servers.json ..."
python - << 'PYEOF' || warn "Uno o più server MCP non raggiungibili — la demo potrebbe fallire"
import json, os, sys, socket, urllib.parse
from pathlib import Path
ROOT = Path(os.environ["PROJECT_ROOT"])
servers_json = json.loads((ROOT / "demo" / "servers.json").read_text())
for srv in servers_json["servers"]:
    url = srv["url"]
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        print(f"  OK   {srv['name']}: {url}")
    except Exception as e:
        print(f"  WARN {srv['name']}: {url} non raggiungibile ({e})", file=sys.stderr)
PYEOF

# ── 8. Avvio demo ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}>> Avvio demo ...${NC}"
echo ""

cd "$PROJECT_ROOT"
python "$PROJECT_ROOT/demo/run_demo.py"
