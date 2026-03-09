# Demo — Ultime 5 News sul Turismo in Emilia Romagna

Demo agentica che usa il framework MCPRuntime per rispondere al prompt:

> **"Mi dici le ultime 5 news sul turismo?"**

## Prerequisiti

| Servizio | URL |
|---|---|
| MCP Server (`api-to-mcp`) | `http://localhost:3001/mcp` |
| OpenSandbox (REST/SSE) | `http://127.0.0.1:44772` |

Dipendenze Python già presenti nel progetto: `fastmcp`, `openai`, `httpx`, `python-dotenv`.

## Configurazione

Le credenziali Azure OpenAI e gli URL dei servizi sono in `demo/.env` (già compilato).
Per sovrascrivere, esportare le variabili d'ambiente prima di eseguire lo script.

## Esecuzione

```bash
# dalla root del progetto
python demo/run_demo.py
```

## Flusso

```
MCPProxy ──► list_tools()           # scopre i tool del server api-to-mcp
    │
    └─► LLM #1 (Azure gpt-4.1)     # prompt + tool definitions → sceglie tool
            │   [log: URL, contesto chars, tools chars]
            │
        MCPProxy.call_tool(...)     # esegue la chiamata MCP
            │
        LLM #2 (Azure gpt-4.1)     # genera risposta finale con i dati
            │   [log: URL, contesto chars]
            │
        OpenSandbox /code           # esegue il print formattato
            │       (fallback: print diretto se non raggiungibile)
            ▼
        STDOUT — news formattate
```

## Log LLM

Per ogni chiamata LLM viene stampato su `stderr`:

```
12:34:56 [INFO] demo - [LLM #1] URL      : https://malb-mg6nfr1i-...
12:34:56 [INFO] demo - [LLM #1] Contesto : 312 chars  (2 messaggi)
12:34:56 [INFO] demo - [LLM #1] Tools    : 2847 chars, 6 tool(s)
...
12:35:02 [INFO] demo - [LLM #2] URL      : https://malb-mg6nfr1i-...
12:35:02 [INFO] demo - [LLM #2] Contesto : 8410 chars  (5 messaggi)
12:35:02 [INFO] demo - [LLM #2] Tools    : none
```
