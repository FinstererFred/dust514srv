# DUST 514 – lokaler Revival-Server

English setup guide (server with Docker, client in RPCS3): [docs/setup_guide_en.md](docs/setup_guide_en.md)

Ein privater Testserver, mit dem der PS3-Client von DUST 514 (NPUB30643, Version 03.19) in RPCS3
wieder bis in die Söldnerunterkunft kommt. Nicht mit CCP oder Sony verbunden.

Stand: Login über RPCN, Charakterauswahl, Laden des Charakters und Willkommensbildschirm laufen ohne
Verbindungsabbruch. Gefechte (Battle-Server) und Speichern von Änderungen gibt es noch nicht.

## Aufbau

| Teil | Sprache | Aufgabe |
|---|---|---|
| `dust_server/` | Python 3 | HTTP-Server auf Port 80/443/8080 (CREST-API), Benachrichtigungs-Streams, Empfang der Client-Logs (UDP 8514) |
| `catma_service/` | Python 2.7 | interner Dienst auf 127.0.0.1:8090: führt CCPs Offline-Handler aus dem Client mit der echten Spieldatenbank (`CATMADB.PICKLE`) aus |
| `client_patch/` | Python 2.7 | wird in `COMMON.SDAT` eingespielt und leitet die Python-Logs des Clients an den Server weiter |
| `tools/` | PowerShell/Python | Start, Patch und Hilfsskripte |

Anfragen laufen so: eigene Handler in `dust_server/crest_app.py` → sonst CCPs Original-Offline-Handler
über `catma_service` → sonst 404 (im Log als `missing` markiert, damit klar ist, was als Nächstes fehlt).

## Voraussetzungen

- RPCS3 mit installiertem DUST 514 (Basisspiel plus Updates 03.18 und 03.19) unter `D:\rpcs3`
- Python 3 und Anaconda (für die Python-2.7-Umgebung)
- Ein RPCN-Konto in RPCS3

## Einrichtung

1. **Python 2.7:** `conda create -p tools\py27 python=2.7`
2. **Client-Module entpacken** (für `catma_service`): `PYTHON.SDAT` und `COMMON.SDAT` aus
   `dev_hdd0\game\NPUB30643\USRDIR\DUSTGAME\` nach `research\extracted_0319\PYTHON` bzw. `\COMMON`
   entpacken (normale ZIP-Archive).
3. **Dev-Zertifikat** für Port 443:
   `openssl req -x509 -newkey rsa:2048 -nodes -keyout dust_server\certs\server.key -out dust_server\certs\server.crt -days 3650 -subj /CN=crest.eveonline.com`
4. **RPCS3**, Spielkonfiguration für NPUB30643, Reiter *Network*:
   - Network Status `Connected`, PSN Status `RPCN`
   - IP/Hosts switches: `crest.eveonline.com=127.0.0.1&&dust.dyn.ccpgamescdn.com=127.0.0.1`
5. **EdgeZlib-Patch** (behebt den schwarzen Bildschirm nach dem Intro): Patch für
   `PPU-ae3f946dfcb103b782f73f1cc5f90587e652f439` (03.19) aus
   [514_CROP-DUSTInG](https://github.com/ProtoDroidBot/514_CROP-DUSTInG) in `D:\rpcs3\patches\` und aktivieren.
6. **Spieldateien** (jeweils vorher sichern):
   - `DUSTGAME\SAKE.INI`: `url = http://127.0.0.1:8080`, optional `networkpackets`/`networkrpc = True`
   - Intro überspringen: `MOVIES\EMPTY.BIK` über `MOVIES\INTRO.BIK` kopieren, dann
     `python tools\set_toc_size.py Movies/Intro.bik`
   - Client-Logs: `python tools\patch_common_sdat.py` (rückgängig mit `--restore`)

## Starten

```powershell
tools\restart_all.ps1 -Label mein_test     # Dienste neu starten, Logs archivieren, Spiel starten
tools\restart_all.ps1 -ServerOnly          # nur die Dienste
tools\start_dust.ps1 -MoveOnly             # Spielfenster klein auf den zweiten Monitor
```

Logs liegen in `dust_server\logs\`: `requests.jsonl` (jede Anfrage mit Antwortquelle), `client.log`
(Python-Log des Clients), ältere Läufe unter `archive\`.

## Web-Admin

Der CREST-Server bringt eine Weboberfläche mit (`dust_server/admin.py`, Seiten in `dust_server/admin_ui/`),
Standard **http://<server>:8088/** (Oberfläche auf Englisch). Sie läuft im selben Prozess, braucht nur die Python-Standardbibliothek und
funktioniert unter Windows wie im Linux-Container.

| Bereich | Was | Gespeichert in |
|---|---|---|
| Status | Host online?, laufender Startbefehl, Neustart nötig?, Gefechtsmitglieder, fehlende Endpunkte, letzte Anfragen | – |
| Battle host | Level/bfid, Modus und Sublevel, Terraform, Licht (Listen aus CATMA), Gefechts-ID/-Name, Teams, Adresse für Clients, Gefechtssuche | `dev_commands.json`, `fake_battle.json` |
| News & documents | MOTD, Wichtige Nachricht, Patchnotes, Community-Events, EULA … | `responses/documents/*.txt` |
| ISK market, AUR store | Marktgruppen und Items aus CATMA, je Item an/aus und Preis | `content/market.json`, `content/aur_store.json` |
| Marketplace start page, Loyalty stores, Login rewards, Wallet | Kacheln, LP-Angebote/-Guthaben, SP/AUR je Login-Tag, ISK/AUR | `content/*.json` |

- **Login:** Token aus `DUST_ADMIN_TOKEN`; ohne Variable erzeugt der Server beim ersten Start
  `dust_server/state/admin_token.txt` (nicht im Repo) und schreibt den Token ins Konsolen-Log. Im Rechenzentrum
  den Port nur per Firewall/SSH-Tunnel oder hinter einem TLS-Proxy freigeben.
- **Optionen:** `--admin-port` / `DUST_ADMIN_PORT` (0 = aus), `--admin-host` / `DUST_ADMIN_HOST`,
  `DUST_CONTENT_DIR` (statt `dust_server/content/`), `DUST_OFFLINE_SERVICE` (statt `http://127.0.0.1:8090`).
- **Moduswechsel:** Ein laufender Host stürzt ab, wenn er den Modus wechselt (0x8cb534). Das UI speichert einen
  anderen Modus deshalb ohne neue Revision und zeigt „Neustart nötig“; der Knopf *Restart host* nutzt
  `DUST_HOST_CONTROL_DIR` (Watchdog im Docker-Container, Datei `restart`) oder `DUST_HOST_RESTART_CMD`
  (unter Windows standardmäßig `toolsestart_host.ps1`, startet nur die Host-Instanz neu). Gleicher Modus
  (Terraform, Licht, Name …) wird mit *Save & apply* sofort als Kartenneustart übernommen.
- Markt, Store und Wallet lädt der Client einmal pro Login; geänderte Dokumente holt er beim nächsten Login.
  Käufe werden noch nicht gespeichert.

## Hinweise

- Dekompilierter CCP-Code, entpackte Archive, Spieldateien und Logs gehören nicht ins Repository
  (siehe `.gitignore`). Die Logs enthalten das RPCN-Ticket mit dem Kontonamen.
- `dust_server/responses/crest_root.json` stammt aus dem Webarchiv (öffentliches CREST-Startdokument
  von `crest-tq.eveonline.com`, September 2015); die Texte in `responses/documents/` sind eigene.
