# NOMAD Duplicator — Garage Zero Lab

Installa **Project NOMAD** e **God's Eye View (GeoIntel)** su Debian 13 x86_64. Prepara Docker Engine e Compose, scarica le revisioni definite in `versions.json`, avvia i servizi e verifica che rispondano.

Testato su **Debian 13**: installazione completata con ripresa dopo correzioni, interfacce web e riavvio dei servizi verificati; 12 test automatici superati.

## Installazione

Servono Debian 13, Python 3, accesso root e Internet. Copia i file del progetto sul PC e apri un terminale nella cartella.

Per vedere il piano senza installare:

```sh
python3 install.py
```

Dopo aver letto e accettato le condizioni dell'installer NOMAD ufficiale, esegui come root:

```sh
python3 install.py --apply --accept-nomad-terms --bind-ip 192.168.1.50
```

Sostituisci l'indirizzo con l'IP LAN del PC. Senza `--bind-ip`, GeoIntel è accessibile soltanto dal PC stesso. NOMAD usa le impostazioni del proprio installer ufficiale.

Apri dal browser:

- NOMAD: `http://IP-DEL-PC:8080/home`
- GeoIntel: `http://IP-DEL-PC:8610/`

NOMAD viene installato in `/opt/project-nomad`; GeoIntel in `/srv/nomad/geointel`. I container mantengono i dati e ripartono con Docker. Completa gli account dalle interfacce web.

## Opzioni utili

- `--skip-nomad`: installa soltanto GeoIntel accanto a NOMAD esistente.
- `--resume`: aggiunto agli stessi argomenti, riprende un tentativo riconosciuto senza rigenerare le credenziali NOMAD.
- `--verify`: controlla i servizi senza installare.
- `--uid` e `--gid`: proprietario Linux dei file GeoIntel; predefiniti 1000.
- `--wsl-shared-mounts`: necessario in Debian WSL; autorizza un servizio persistente che rende condivisi i mount Linux prima di Docker, per il raccoglitore dischi NOMAD. L'avvio al login Windows resta da configurare.

## Gestione GeoIntel

```sh
docker compose -f /srv/nomad/geointel/compose.json logs --tail 60
docker compose -f /srv/nomad/geointel/compose.json stop
docker compose -f /srv/nomad/geointel/compose.json up -d
```

L'installer conserva le installazioni esistenti e si interrompe se trova configurazioni incompatibili. Installa i servizi di base: voce locale, MCP, modelli AI, librerie multimediali e cartografia offline richiedono configurazioni aggiuntive. GeoIntel usa anche fonti Internet; le chiavi API non sono incluse.

Progetti originali: [Project NOMAD](https://github.com/Crosstalk-Solutions/project-nomad) e [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view).
