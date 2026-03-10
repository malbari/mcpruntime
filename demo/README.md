# Demo — MCPRuntime + OpenSandbox

Demo di integrazione che mostra come usare MCPRuntime in un servizio
server-side multi-utente. Il codice è organizzato in due fasi distinte:
**startup** (una volta, all'avvio del server) e **per-richiesta** (per ogni
prompt utente).

---

## Prerequisiti

| Servizio | URL default |
|---|---|
| MCP Server (`api_to_mcp`) | `http://localhost:3001/mcp` |
| OpenSandbox execd | `http://127.0.0.1:44772` |

I server MCP sono configurati in `demo/servers.json`.
Le credenziali Azure OpenAI e gli URL dei servizi sono in `demo/.env`.

---

## Esecuzione

```bash
./demo/run_demo.sh
```

Lo script crea il virtual env, installa le dipendenze, verifica i servizi e
avvia la demo.

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│  STARTUP  (una volta, all'avvio del processo server)                │
│                                                                     │
│  1. Genera stub                                                     │
│     servers/<server>/<tool>.py  ←  MCP tool definitions            │
│     (idempotente: salta se già presenti)                            │
│                                                                     │
│  2. Proxy MCP  :porta_libera                                        │
│     Bridge HTTP: container → host → server MCP                     │
│     Condiviso tra tutte le richieste                                │
│                                                                     │
│  3. Agent (create_agent)                                            │
│     • ToolSelector  — modello embeddings all-MiniLM-L6-v2 su MPS   │
│     • CodeGenerator — client LLM via litellm (Azure OpenAI)        │
│     Costoso (~4s): allocato una sola volta                          │
│                                                                     │
│  4. Tool discovery  →  AppState.discovered_tools                    │
│     Legge stub da disco, costruisce il catalogo. Cachato.           │
│                                                                     │
│  5. Workspace upload nel container OpenSandbox                      │
│     POST /directories  — mkdir -p                                   │
│     POST /files/upload — multipart upload di stub + proxy client   │
│     I file restano su disco del container: non servono ricariche.   │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ AppState (read-only, thread-safe)
┌─────────────────────────────────────────────────────────────────────┐
│  PER RICHIESTA  (per ogni prompt utente)                            │
│                                                                     │
│  1. Tool selection                                                  │
│     Ricerca semantica (embeddings) sul catalogo cachato             │
│                                                                     │
│  2. Build tool info                                                 │
│     Raccoglie nome/server/descrizione dei tool selezionati          │
│     → passati come JSON a LLM #2 nel container                      │
│                                                                     │
│  3. Code generation — LLM #1 (orchestratore, sull'host)            │
│     Genera schema fisso:                                            │
│       response = tool_call(...)        ← LLM #1 sceglie i param    │
│       display_code = ask_llm(response_data, available_tools)        │
│       exec(display_code, globals())                                 │
│                                                                     │
│  4. Kernel reset                                                    │
│     DELETE /code/contexts — azzera stato Jupyter nel container      │
│     Isola ogni richiesta da quelle precedenti                       │
│                                                                     │
│  5. Esecuzione nel container  (flusso in due stadi)                 │
│     POST /code → execd (NDJSON streaming)                           │
│     a. Codice chiama tool MCP → /call-tool proxy → dati reali       │
│     b. ask_llm() → /ask-llm proxy → LLM #2 riceve dati + tool list │
│     c. LLM #2 genera display code → exec() nella stessa sessione   │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ stdout del container (LLM #2 output)
```

---

## API del modulo

Le due funzioni pubbliche principali di `run_demo.py` rispecchiano il
ciclo di vita di un server reale:

```python
# In un server FastAPI/Flask/aiohttp — pseudocodice
from demo.run_demo import startup, handle_prompt

app_state = None

@on_startup
async def server_startup():
    global app_state
    app_state = await startup()        # una volta, al boot

@on_request
async def handle(prompt: str) -> str:
    return await handle_prompt(app_state, prompt)   # per ogni utente

@on_shutdown
def server_shutdown():
    app_state.proxy_srv.shutdown()
```

---

## Multi-utente in produzione

| Componente | Demo (un utente) | Produzione (multi-utente) |
|---|---|---|
| Kernel execd | Reset globale prima di ogni run | Un context_id per utente (`POST /code/context`) |
| Container | Uno condiviso | Sandbox pool (un container per utente) |
| AppState | Singleton | Singleton — è già thread-safe in lettura |
| Proxy MCP | Porta fissa post-startup | Invariato |

Per i contesti per-utente:

```python
# Crea kernel isolato
ctx = httpx.post(f"{EXECD_URL}/code/context", json={"language": "python"}).json()

# Esegui su quel kernel
httpx.post(f"{EXECD_URL}/code", json={"context": {"language": "python", "id": ctx["id"]}, "code": ...})

# Cleanup dopo la richiesta
httpx.delete(f"{EXECD_URL}/code/contexts/{ctx['id']}")
```

---

## Configurazione servers.json

```json
{
  "servers": [
    {
      "name": "api_to_mcp",
      "url": "http://localhost:3001/mcp",
      "description": "API turismo ed eventi"
    }
  ]
}
```

Aggiungere un server = aggiungere un elemento all'array. `startup()` genera
gli stub e abilita il routing del proxy automaticamente.

---

## Struttura file

```
demo/
├── run_demo.sh        # setup venv + avvio demo
├── run_demo.py        # startup() + handle_prompt() + AppState
├── servers.json       # configurazione server MCP
├── .env               # credenziali (non in git)
└── .venv/             # virtual env (creato da run_demo.sh)
```
