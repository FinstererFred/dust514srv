# DUST 514 – local revival server

Setup guide (server with Docker, client in RPCS3): [docs/setup_guide_en.md](docs/setup_guide_en.md)

A private test server that gets the PS3 client of DUST 514 (NPUB30643, version 03.19) in RPCS3 back into
the Mercenary Quarters. Not affiliated with CCP or Sony.

Status: login via RPCN, character selection, loading the character and the welcome screen work without the
connection dropping. Battles (battle server) and saving changes are not available yet.

## Layout

| Part | Language | Purpose |
|---|---|---|
| `dust_server/` | Python 3 | HTTP server on ports 80/443/8080 (CREST API), notification streams, receiving the client logs (UDP 8514) |
| `catma_service/` | Python 2.7 | internal service on 127.0.0.1:8090: runs CCP's offline handlers from the client against the real game database (`CATMADB.PICKLE`) |
| `client_patch/` | Python 2.7 | gets injected into `COMMON.SDAT` and forwards the client's Python logs to the server |
| `tools/` | PowerShell/Python | start, patch and helper scripts |

Requests are handled like this: own handlers in `dust_server/crest_app.py` → otherwise CCP's original offline
handlers via `catma_service` → otherwise 404 (marked as `missing` in the log, so it is clear what is needed next).

## Requirements

- RPCS3 with DUST 514 installed (base game plus updates 03.18 and 03.19) under `D:\rpcs3`
- Python 3 and Anaconda (for the Python 2.7 environment)
- An RPCN account in RPCS3

## Setup

1. **Python 2.7:** `conda create -p tools\py27 python=2.7`
2. **Extract the client modules** (for `catma_service`): extract `PYTHON.SDAT` and `COMMON.SDAT` from
   `dev_hdd0\game\NPUB30643\USRDIR\DUSTGAME\` to `research\extracted_0319\PYTHON` and `\COMMON`
   respectively (plain ZIP archives).
3. **Dev certificate** for port 443:
   `openssl req -x509 -newkey rsa:2048 -nodes -keyout dust_server\certs\server.key -out dust_server\certs\server.crt -days 3650 -subj /CN=crest.eveonline.com`
4. **RPCS3**, game configuration for NPUB30643, *Network* tab:
   - Network Status `Connected`, PSN Status `RPCN`
   - IP/Hosts switches: `crest.eveonline.com=127.0.0.1&&dust.dyn.ccpgamescdn.com=127.0.0.1`
5. **EdgeZlib patch** (fixes the black screen after the intro): put the patch for
   `PPU-ae3f946dfcb103b782f73f1cc5f90587e652f439` (03.19) from
   [514_CROP-DUSTInG](https://github.com/ProtoDroidBot/514_CROP-DUSTInG) into `D:\rpcs3\patches\` and enable it.
6. **Game files** (back each one up first):
   - `DUSTGAME\SAKE.INI`: `url = http://127.0.0.1:8080`, optionally `networkpackets`/`networkrpc = True`
   - Skip the intro: copy `MOVIES\EMPTY.BIK` over `MOVIES\INTRO.BIK`, then
     `python tools\set_toc_size.py Movies/Intro.bik`
   - Client logs: `python tools\patch_common_sdat.py` (undo with `--restore`)

## Running

```powershell
tools\restart_all.ps1 -Label my_test       # restart the services, archive the logs, start the game
tools\restart_all.ps1 -ServerOnly          # services only
tools\start_dust.ps1 -MoveOnly             # move the game window, small, to the second monitor
```

Logs are in `dust_server\logs\`: `requests.jsonl` (every request with the source of the answer), `client.log`
(the client's Python log), older runs under `archive\`.

## Web admin

The CREST server comes with a web interface (`dust_server/admin.py`, pages in `dust_server/admin_ui/`),
default **http://<server>:8088/**. It runs in the same process, needs only the Python standard library and
works on Windows as well as in the Linux container.

| Section | What | Stored in |
|---|---|---|
| Status | host online?, current start command, restart needed?, battle members, missing endpoints, recent requests | – |
| Battle host | level/bfid, mode and sublevel, terraform, lighting (lists from CATMA), battle ID/name, teams, address for clients, battle finder | `dev_commands.json`, `fake_battle.json` |
| News & documents | MOTD, important message, patch notes, community events, EULA … | `responses/documents/*.txt` |
| ISK market, AUR store | market groups and items from CATMA, each item on/off with a price | `content/market.json`, `content/aur_store.json` |
| Marketplace start page, Loyalty stores, Login rewards, Wallet | tiles, LP offers/balances, SP/AUR per login day, ISK/AUR | `content/*.json` |

- **Login:** token from `DUST_ADMIN_TOKEN`; without the variable the server creates
  `dust_server/state/admin_token.txt` (not in the repo) on first start and writes the token to the console log. In a
  data center, expose the port only through a firewall/SSH tunnel or behind a TLS proxy.
- **Options:** `--admin-port` / `DUST_ADMIN_PORT` (0 = off), `--admin-host` / `DUST_ADMIN_HOST`,
  `DUST_CONTENT_DIR` (instead of `dust_server/content/`), `DUST_OFFLINE_SERVICE` (instead of `http://127.0.0.1:8090`).
- **Mode changes:** A running host crashes when it changes mode (0x8cb534). The UI therefore saves a different
  mode without a new revision and shows "restart needed"; the *Restart host* button uses
  `DUST_HOST_CONTROL_DIR` (watchdog in the Docker container, file `restart`) or `DUST_HOST_RESTART_CMD`
  (on Windows `tools\restart_host.ps1` by default, which restarts only the host instance). The same mode
  (terraform, lighting, name …) is applied immediately as a map restart with *Save & apply*.
- The client loads market, store and wallet once per login; it fetches changed documents at the next login.
  Purchases are not saved yet.

## Notes

- Decompiled CCP code, extracted archives, game files and logs do not belong in the repository
  (see `.gitignore`). The logs contain the RPCN ticket with the account name.
- `dust_server/responses/crest_root.json` comes from the Web Archive (public CREST root document
  of `crest-tq.eveonline.com`, September 2015); the texts in `responses/documents/` are our own.
