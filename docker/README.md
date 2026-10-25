# DUST 514 – Gefechts-Host im Docker-Container

Standalone-Host für einen Linux-Server ohne GPU. Drei Container, alle im Host-Netzwerk:

| Dienst | Image | Aufgabe |
|---|---|---|
| `host` | `dust514-host` (Ubuntu 26.04) | RPCS3, aus dem Quellcode gebaut mit `rpcs3_patches/*.patch`, läuft `--headless` mit Null-Renderer und startet die Karte als UE3-Listen-Server (UDP 7777); ein Watchdog startet RPCS3 bei Absturz, Hänger oder auf Anfrage neu |
| `crest` | `dust514-crest` (Python 3.13) | `dust_server/` (CREST-API, Gefechtssuche, Dev-Befehle für den Host) |
| `catma` | `dust514-catma` (Python 2.7) | `catma_service/` (CCPs Offline-Handler mit der CATMA-Datenbank) |

Warum das ohne GPU geht: `docs/battle_feasibility.md`, Experiment 9, Nachtrag „Null-Renderer gelöst“.

## Voraussetzungen

- Linux-Server mit Docker und Compose v2, x86-64 mit AVX2, mindestens 8 Kerne und 16 GB RAM (Richtwert: Beim Test
  liefen sechs SPU-Threads mit je ~80 % plus RSX-, PPU- und Python-Threads)
- Rund 15 GB Platz: Daten ~3 GB, RPCS3-Build ~5 GB, Caches
- Der Datenordner (siehe unten), lokal erzeugt mit `tools/export_host_data.ps1`
- Ein **eigenes RPCN-Konto für den Host**. Ein Konto kann nicht zweimal gleichzeitig angemeldet sein.

## Datenordner (`DUST_DATA`, außerhalb des Repos)

```
$DUST_DATA/
  extracted_0319/                 entpackte PYTHON.SDAT/COMMON.SDAT (für catma)
  rpcs3/                          → /data im host-Container
    config/rpcs3/                 = $XDG_CONFIG_HOME/rpcs3
      custom_configs/config_NPUB30643.yml   Null-Renderer, Frame limit Auto (unter Linux ohne config/-Unterordner)
      patch_config.yml, rpcn.yml
      dev_hdd0/game/NPUB30643/    Spiel mit gepatchter COMMON.SDAT (Dev-Hook, Log-Weiterleitung) und SAKE.INI
      dev_hdd0/home/              Benutzerprofil mit Lizenz (.rap)
      dev_flash/                  PS3-Firmware
      patches/                    EdgeZlib-Patch
    cache/rpcs3/                  RPCS3.log, PPU/SPU-Caches (entsteht beim ersten Start)
    control/                      restart, stop, status.json (Watchdog)
```

Erzeugen auf dem Windows-PC und hochladen:

```powershell
tools\export_host_data.ps1 -Out E:\dust514-data -RpcnConfig <rpcn.yml des Host-Kontos>
```

## Start

```bash
cd docker
cp .env.example .env          # DUST_DATA anpassen
docker compose up -d --build  # der erste Build kompiliert RPCS3 (je nach CPU 20–60 Minuten)
docker compose logs -f host
```

Der erste Start des Hosts kompiliert zusätzlich die PPU/SPU-Caches (lokal etwa 4 Minuten bis zur Karte, danach
rund 100 Sekunden). Deshalb beginnt die Hänger-Erkennung erst nach `STARTUP_GRACE` Sekunden (Standard 1200).

**Docker Desktop (Windows/macOS):** Dessen Host-Networking leitet UDP-Antworten nicht zurück, Spieler bekommen dann
keine Antwort vom Listen-Server. Dafür gibt es `compose.desktop.yaml`. Damit teilen sich alle Dienste das Netz des
`host`-Containers, und die Ports werden veröffentlicht:

```bash
docker compose -f compose.yaml -f compose.desktop.yaml up -d
```

`rpcn.yml` des Hosts zeigt dann auf `host.docker.internal:31313`, wenn der RPCN-Server auf dem PC läuft (dort
`Host=0.0.0.0` in `rpcn.cfg`). Wird der `host`-Container neu erzeugt, müssen `crest` und `catma` mit neu erzeugt
werden (gemeinsamer Netz-Namespace). Ein Neustart über den Watchdog betrifft nur RPCS3 im Container.

## Steuerung

- Neustart des Hosts, z. B. nach einem Moduswechsel (der laufende Host kann den Modus nicht wechseln):
  `touch $DUST_DATA/rpcs3/control/restart`
- Anhalten, bis die Datei wieder weg ist: `touch $DUST_DATA/rpcs3/control/stop`
- Zustand: `$DUST_DATA/rpcs3/control/status.json` (`state`, `pid`, `restarts`, `reason`)
- Der Watchdog startet RPCS3 auch neu, wenn das Spiel im Host den CREST-Server länger als `HEARTBEAT_TIMEOUT`
  Sekunden (Standard 120) nicht mehr abfragt (`GET /dev/host/heartbeat/`). Das passiert zum Beispiel nach einem
  Neustart von `crest`: Das Python des Spiels stirbt dann, während RPCS3 weiterläuft.
- Web-Admin: `http://<server>:8088/`, „Restart host“ nutzt dieselbe `restart`-Datei.
- Dev-Befehle (`/dev/commands/`, `/dev/battle/members/`) bekommt nur der Host, also Anfragen von `127.0.0.1`
  (einstellbar mit `DUST_HOST_PEERS` im `crest`-Container). Andere Clients mit unserem `COMMON.SDAT`-Patch
  bekommen eine leere Liste. Sonst würden sie das Host-Rezept ausführen und ein eigenes Listen-Match starten.
- Modus und Karte: `dust_server/fake_battle.json` und `dev_commands.json` (bzw. `dust_server/set_host_mode.py`)

## Netz

| Port | Zweck |
|---|---|
| UDP 7777 | UE3-Listen-Server (Spieler verbinden sich hierher) |
| TCP 8080 (und 80/443) | CREST-API für die Clients |
| TCP 8088 | Web-Admin (`ADMIN_PORT`; Token per `ADMIN_TOKEN`, sonst in `dust_server/state/admin_token.txt`) |
| UDP 8514 | Log-Weiterleitung gepatchter Clients (optional) |

Für Spieler außerhalb des Servers:
- In `dust_server/fake_battle.json` muss `target_listen` die öffentliche Adresse des Servers tragen, nicht
  127.0.0.1.
- Clients brauchen `SAKE.INI` mit `url = http://<server>:8080` und in RPCS3 die IP-Umleitung
  `crest.eveonline.com=<server>&&dust.dyn.ccpgamescdn.com=<server>`.
- Jeder Spieler braucht ein eigenes RPCN-Konto.

## Stand

Getestet am 2026-10-25 unter Docker Desktop (WSL2, Ryzen 9 5900X) mit `compose.desktop.yaml`:
- Das Image baut (RPCS3 `0.0.43-1-e53ac18f` mit Patch, ~10 Minuten mit 12 Jobs, 978 MB ohne Spieldaten).
- Der Host meldet sich per RPCN (lokaler Server) an, ist nach etwa 4 Minuten (erster Start) bzw. 100 Sekunden in
  den Merc Quarters und startet die Ambush-Karte. Es gibt keine Flip-Meldungen mehr.
- Client 2 (Windows, Vulkan) tritt über die Gefechtssuche bei, verbindet sich über UDP 7777 und spawnt
  (`docs/battle_mp_docker_client2.png`).
- Last: Der Container braucht etwa 7,3 Kerne (sechs SPU-Threads mit je ~93 %, RSX-Thread ~100 %, PPU ~60 %) und
  2–4 GB RAM.
- Offen: der Linux-Server mit reinem Host-Netz, mehr als zwei Spieler, längeres Spielen. Warum der RSX-Thread
  auch ohne Flip-Schleife einen vollen Kern braucht, ist ebenfalls noch ungeklärt.
