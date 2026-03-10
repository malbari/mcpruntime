# Agent Skills — MCP Servers

Scegli il server MCP più specifico per rispondere al prompt utente.
Non inventare valori per parametri filtro; omettili se non esplicitamente richiesti.

## lightrag-server
**Contenuto**: Documentazione pubblica sanitaria di ASST Lariana (ospedali, reparti, servizi); documenti sui centri di visita in Arabia Saudita.
**Usa per**: domande su ASST Lariana, documenti clinici/sanitari, informazioni centri Arabia Saudita, bandi, gare, anestesia, sintesi, riassunto, ricerca semantica su documenti.
**Tool principale**: query_document — esegue query semantiche su documenti.

## dbhub-server
**Contenuto**: Database relazionale con tabelle di episodi clinici sanitari (diagnosi, reparti, ricoveri).
**Usa per**: interrogazioni su dati clinici strutturati, statistiche ospedaliere, ricerche per diagnosi o reparto.

## api-to-mcp
**Contenuto**: API ufficiali turismo Regione Emilia Romagna — news, eventi, città, immagini, itinerari, luoghi di interesse.
**Usa per**: notizie turistiche, eventi locali, informazioni su comuni/luoghi dell'Emilia Romagna.

## mcp-server-chart
**Contenuto**: Servizi di rendering grafico (bar chart, line chart, pie chart) per chat web.
**Usa per**: visualizzare dati numerici o serie temporali già disponibili in forma grafica. Richiede sempre dati in input.

## basic-server-preact
**Contenuto**: MCP app che espone l'orario corrente del server (timestamp UTC e locale).
**Usa per**: richieste di ora/data corrente, timestamp.

## budget-allocator-server
**Contenuto**: MCP app per la definizione e gestione di budget (allocazione voci di costo, totali, percentuali).
**Usa per**: calcoli budget, piani di spesa, allocazione risorse finanziarie.

## map-server
**Contenuto**: MCP app per visualizzare mappe interattive CesiumJS e geocodificare luoghi via OpenStreetMap.
**Usa per**: mostrare una mappa, geolocalizzare indirizzi/luoghi, visualizzare coordinate geografiche.
