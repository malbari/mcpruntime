# Agent Skills

Scegli la skill (servizio) più specifica per rispondere al prompt utente.
Non inventare valori per parametri filtro; omettili se non esplicitamente richiesti.

## lightrag-server
**Contenuto**: Documentazione pubblica sanitaria di ASST Lariana (ospedali, reparti, servizi); documenti sui centri di visita in Arabia Saudita.
**Usa per**: domande su ASST Lariana, documenti clinici/sanitari, informazioni centri Arabia Saudita, bandi, gare, anestesia, sintesi, riassunto, ricerca semantica su documenti.
**Tool principale**: query_document — esegue query semantiche su documenti.

## dbhub-server
**Contenuto**: Database relazionale con tabelle di episodi clinici sanitari (diagnosi, reparti, ricoveri, pazienti, patologie).
**Usa per**: interrogazioni SQL su dati clinici strutturati, statistiche ospedaliere, distribuzione pazienti per patologia principale, aggregazione dati, ricerche per diagnosi o reparto.
**Workflow OBBLIGATORIO a due step**:
  1. Lo step agent-generated chiama `search_objects(object_type='table', detail_level='full')` e passa lo schema allo step sandbox-generated.
     ATTENZIONE: `detail_level` accetta SOLO `'names'`, `'summary'`, `'full'` — NON `'columns'`.
  2. Lo step sandbox-generated (può essere invocato ricorsivamente) legge i nomi REALI di tabelle e colonne dallo schema, poi chiama `execute_sql` con SQL corretto.
  Lo step agent-generated NON deve scrivere SQL — non conosce i nomi reali delle colonne prima dell'esecuzione.
  ATTENZIONE parametro: `execute_sql` accetta il parametro `sql` (NON `query`). Esempio:
  `call_mcp_tool('dbhub-server', 'execute_sql', {'sql': 'SELECT ...'})`
  ATTENZIONE risposta: `execute_sql` restituisce `{'success': True, 'data': {'rows': [...]}}`.
  Per accedere alle righe usare SEMPRE `result['data']['rows']` — MAI `result['rows']`.

## api-to-mcp
**Contenuto**: API ufficiali turismo Regione Emilia Romagna — news, eventi, città, immagini, itinerari, luoghi di interesse.
**Usa per**: notizie turistiche, eventi locali, informazioni su comuni/luoghi dell'Emilia Romagna.

## mcp-server-chart
**Contenuto**: Servizi di rendering grafico (bar chart, line chart, pie chart, grafico a torta, grafico a barre) per chat web.
**Usa per**: visualizzare dati numerici o serie temporali in forma grafica; grafico a torta per distribuzione percentuale; grafico patologie pazienti; richiede sempre dati in input.
**Tool principale**: generate_pie_chart per distribuzioni percentuali a torta.
**Formato dati OBBLIGATORIO per generate_pie_chart**: il parametro `data` deve essere una lista di dizionari con chiavi `category` e `value`, esempio:
  `data=[{"category": "Diabete", "value": 5}, {"category": "Ipertensione", "value": 3}]`
  ATTENZIONE: SQL restituisce i valori sempre come STRINGHE — converti SEMPRE con int(): `"value": int(r["value"])`.
  NON passare rows direttamente. NON usare `label`.

## basic-server-preact
**Contenuto**: MCP app che espone l'orario corrente del server (timestamp UTC e locale).
**Usa per**: richieste di ora/data corrente, timestamp.

## budget-allocator-server
**Contenuto**: MCP app per la definizione e gestione di budget (allocazione voci di costo, totali, percentuali).
**Usa per**: calcoli budget, piani di spesa, allocazione risorse finanziarie.

## map-server
**Contenuto**: MCP app per visualizzare mappe interattive CesiumJS e geocodificare luoghi via OpenStreetMap.
**Usa per**: mostrare una mappa, geolocalizzare indirizzi/luoghi, visualizzare coordinate geografiche.
