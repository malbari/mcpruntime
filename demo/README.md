# Demo — MCPRuntime + OpenSandbox

Demo di integrazione che mostra come usare MCPRuntime in un servizio
server-side multi-utente. Il codice è organizzato in due fasi distinte:
**startup** (una volta, all'avvio del server) e **per-richiesta** (per ogni
prompt utente).

---

## Prerequisiti

| Servizio | URL default |
|---|---|
| OpenSandbox execd | `http://localhost:44772` |
| lightrag-server | `http://localhost:8092/mcp` |
| dbhub-server | `http://localhost:8180/mcp` |
| api-to-mcp | `http://localhost:3001/mcp` |
| mcp-server-chart | `http://localhost:1122/mcp` |
| basic-server-preact | `http://localhost:3101/mcp` |
| budget-allocator-server | `http://localhost:3107/mcp` |
| map-server | `http://localhost:3112/mcp` |

I server MCP sono configurati in `demo/servers.json`.
Le credenziali Azure OpenAI e gli URL dei servizi sono in `demo/.env`.

---

## Esecuzione

```bash
./demo/run_demo.sh
```

Lo script crea il virtual env, installa le dipendenze, verifica i servizi e
avvia la demo iterando su tutti i prompt definiti in `demo/test-prompts.txt`.

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│  STARTUP  (una volta, all'avvio del processo server)                │
│                                                                     │
│  1. Genera stub                                                     │
│     servers/<server>/<tool>.py  ←  MCP tool definitions            │
│     (idempotente: salta se già presenti)                            │
│     I docstring includono descrizione completa + vincoli schema     │
│     (enum, maxLength, range) per migliorare tool selection          │
│                                                                     │
│  2. Proxy MCP  :porta_libera                                        │
│     Bridge HTTP: container → host → server MCP                     │
│     Condiviso tra tutte le richieste                                │
│     Endpoint:  POST /call-tool  •  POST /ask-llm                   │
│     Errori MCP: HTTP 200 + {"__mcp_error__": "..."} (no 500)       │
│                                                                     │
│  3. Agent (create_agent)                                            │
│     • ToolSelector  — hybrid search BM25 + dense embeddings        │
│       (paraphrase-multilingual-MiniLM-L12-v2, multilingue)         │
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
│  1. Tool selection — Hybrid search BM25 + Dense + RRF              │
│     • BM25: keyword matching preciso (termini letterali)            │
│     • Dense: cosine similarity (embeddings multilingue)             │
│     • RRF: Reciprocal Rank Fusion combina i due segnali             │
│     Gate: tool incluso se dense ≥ threshold OPPURE bm25 > 0        │
│                                                                     │
│  2. Build tool info                                                 │
│     Raccoglie stub (nome, server, descrizione) di TUTTI i candidati │
│     → passati a LLM #1 per la scelta finale del tool                │
│                                                                     │
│  3. Code generation — LLM #1 (orchestratore, sull'host)            │
│     Riceve tutti gli stub candidati e sceglie autonomamente         │
│     Genera schema fisso:                                            │
│       response = tool_call(...)    ← parametri dedotti dal prompt   │
│       display_code = ask_llm(response_data, available_tools)        │
│       exec(display_code, globals())                                 │
│     Regole: lingua=italiano, limit≤5, nessun valore filtro inventato│
│                                                                     │
│  4. Kernel reset                                                    │
│     DELETE /code/contexts — azzera stato Jupyter nel container      │
│     Isola ogni richiesta da quelle precedenti                       │
│     Preamble iniezione: ricarica mcp_client e sovrascrive           │
│     _PROXY_PORT e _SANDBOX_HOST a runtime                           │
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

## Tool Selection: Hybrid Search

La selezione dei tool combina due segnali complementari tramite
**Reciprocal Rank Fusion (RRF)**:

| Segnale | Punti di forza | Limite |
|---|---|---|
| BM25 (keyword) | Termini letterali (es. "news" → `news_get`) | Non capisce sinonimi |
| Dense (embeddings) | Sinonimi e concetti correlati | Bias verso tool con testo lungo |
| **RRF** | **Bilancia entrambi** | — |

La formula RRF è: `score = 1/(60+rank_bm25) + 1/(60+rank_dense)`

Il gate di inclusione è OR: un tool viene selezionato se
`dense ≥ threshold` **oppure** `bm25 > 0`.

Il log di ogni esecuzione mostra, per i Top-5:
```
Top-1: api-to-mcp.news_get  (rrf=0.0318  dense=0.172  bm25=3.547  dense_rank=5  bm25_rank=1)
Top-2: api-to-mcp.events_get  (rrf=0.0311  dense=0.260  bm25=0.000  dense_rank=1  bm25_rank=8)
```

---

## Batch testing con test-prompts.txt

La demo legge i prompt da `demo/test-prompts.txt` e li esegue in sequenza,
separando ogni test con una riga di `=` (120 caratteri) per leggibilità.

```
# Commento — riga ignorata
Mi dici le ultime 5 news sul turismo?
Mostrami una mappa di Bologna
```

Le righe che iniziano con `#` e le righe vuote vengono saltate.
Aggiungere prompt = aggiungere righe al file. Nessuna modifica al codice.

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
      "name": "api-to-mcp",
      "url": "http://localhost:3001/mcp",
      "description": "API Emilia Romagna Turismo"
    }
  ]
}
```

Aggiungere un server = aggiungere un elemento all'array. `startup()` genera
gli stub e abilita il routing del proxy automaticamente.

Il nome (`name`) viene usato come nome della sottodirectory in `servers/`
e come chiave di routing nel proxy: deve corrispondere esattamente al nome
della cartella generata dagli stub.

---

## Struttura file

```
demo/
├── run_demo.sh        # setup venv + avvio demo
├── run_demo.py        # startup() + handle_prompt() + AppState
├── servers.json       # configurazione 7 server MCP
├── test-prompts.txt   # prompt di test eseguiti in batch
├── .env               # credenziali (non in git)
└── .venv/             # virtual env (creato da run_demo.sh)
```
