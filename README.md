# NOMAD Duplicator — Garage Zero Lab

Installa **Project NOMAD** e **God's Eye View originale, versione 0.3.0**, su Debian 13 x86_64. Prepara Docker Engine e Compose, scarica le revisioni definite in `versions.json` e avvia i servizi.

GeoIntel funziona **online**, con sorgenti upstream invariati: cartografia Esri/OSM, rilievi, voli, satelliti, terremoti, telecamere, meteo e gli altri livelli previsti dall'originale. Le fonti possono avere ritardi o richiedere chiavi. Non vengono aggiunti modalità offline, assistenti locali, ponti MCP o limiti CPU personalizzati.

Testato su **Debian 13**: build ufficiale completata, globo e flussi voli/terremoti verificati dal browser LAN; 16 test degli script superati. La fluidità del globo dipende soprattutto dal browser e dalla GPU del dispositivo che lo visualizza.

## Installazione

Servono Debian 13, Python 3, accesso root e Internet. Copia il progetto sul PC e apri un terminale nella cartella.

Per vedere il piano senza installare:

```sh
python3 install.py
```

Dopo aver letto e accettato le condizioni NOMAD, esegui come root:

```sh
python3 install.py --apply --accept-nomad-terms --bind-ip 192.168.1.50
```

Sostituisci l'indirizzo con l'IP LAN del PC. Senza `--bind-ip`, GeoIntel è raggiungibile solo dal PC stesso. NOMAD usa le impostazioni del proprio installer ufficiale.

- NOMAD: `http://IP-DEL-PC:8080/home`
- GeoIntel originale: `http://IP-DEL-PC:8610/`

I file si trovano in `/opt/project-nomad` e `/srv/nomad/geointel`. Dati e cache persistono; i container ripartono con Docker. La memoria del container GeoIntel è limitata a 2 GiB per convivere con NOMAD. Le chiavi API non sono incluse e non vengono copiate da installazioni precedenti.

## Opzioni

- `--skip-nomad`: installa soltanto GeoIntel accanto a NOMAD esistente.
- `--resume`: riprende un tentativo riconosciuto usando gli stessi argomenti.
- `--verify`: verifica i servizi senza installare.
- `--uid` e `--gid`: proprietario dei file GeoIntel, predefiniti 1000.
- `--wsl-shared-mounts`: autorizza in Debian WSL i mount Linux condivisi necessari al raccoglitore dischi NOMAD.

## Sostituire il vecchio GeoIntel personalizzato

`restore_original.py` è dedicato alla precedente installazione Garage Zero Lab in `/srv/nomad/geointel`, con progetto Docker `nomad-geointel`, utente UID/GID 1000 e ingresso web sulla porta locale 8610. Richiede Docker già installato; non è un aggiornamento generico per installazioni diverse.

Come root:

```sh
python3 restore_original.py --apply
```

Prepara `app-original`, costruisce e verifica la build prima del cambio, mantiene il vecchio servizio se la build fallisce e tenta il ripristino in caso di mancato avvio. Nessuna chiave precedente viene importata. Apri `http://geointel.local/` e controlla il globo, poi completa la pulizia:

```sh
python3 restore_original.py --cleanup
```

La pulizia elimina la vecchia copia GeoIntel e il suo servizio vocale/MCP, conservando NOMAD e gli altri servizi. I vecchi link GeoIntel vengono reindirizzati alla pagina originale. Dopo la pulizia la copia precedente non è più disponibile per il ripristino.

## Microfono dal PC Windows

Il microfono richiede HTTPS oppure un indirizzo localhost: su `http://geointel.local` il browser lo blocca. Senza modificare il progetto originale, apri in PowerShell un tunnel SSH verso il server:

```powershell
ssh -N -L 127.0.0.1:18610:127.0.0.1:8610 UTENTE@IP-DEL-SERVER
```

Lascia il terminale aperto e visita `http://localhost:18610/`, poi consenti il microfono. Per Gemini/OpenAI serve anche la configurazione del provider prevista dal progetto: rendere disponibile il microfono non configura le chiavi né autorizza consumi a pagamento.

## Gestione

Per una nuova installazione:

```sh
docker compose -f /srv/nomad/geointel/compose.json logs --tail 60
docker compose -f /srv/nomad/geointel/compose.json stop
docker compose -f /srv/nomad/geointel/compose.json up -d
```

Dopo la sostituzione del vecchio GeoIntel, usa invece `compose.original.json`.

La grafica degli edifici fotorealistici mostrata nelle demo richiede un token **Cesium ion** idoneo o una chiave **Google Maps**. Le condizioni e le quote dei fornitori si applicano; voce OpenAI/Gemini e altri servizi opzionali richiedono la configurazione prevista dall'originale. Nessuna chiamata AI a pagamento viene attivata automaticamente.

Progetti originali: [Project NOMAD](https://github.com/Crosstalk-Solutions/project-nomad) e [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view).
