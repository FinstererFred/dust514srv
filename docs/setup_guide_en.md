# DUST 514 revival – setup guide

How to run your own DUST 514 battle server with Docker and connect to it with the PS3 client in RPCS3.
This is a private, experimental project, not affiliated with CCP Games or Sony. You need your own copy of the
game and of the PS3 firmware; neither is distributed here.

Contents:
1. [Server setup with Docker](#1-server-setup-with-docker)
2. [Client setup (the game in RPCS3)](#2-client-setup-the-game-in-rpcs3)

## How it works

DUST 514 battles originally ran on CCP's own battle servers, which were never released. This project hosts a
battle on a PS3 client instead: an RPCS3 instance on the server runs the game as an Unreal Engine 3
**listen server** (no GPU needed, it renders nothing). Next to it run our replacement for CCP's backend
(CREST API, battle finder, web admin) and a service that answers game data requests from the client's own
database.

| Container | Purpose | Ports |
|---|---|---|
| `host` | RPCS3 (built from source with our patches) running the battle map, plus a watchdog that restarts it | UDP 7777 |
| `crest` | Backend for all clients (CREST API, battle finder) and the web admin | TCP 8080, 80, 443; TCP 8088 (admin) |
| `catma` | Game data service (internal only) | 127.0.0.1:8090 |
| `rpcn` | RPCN server the host signs in to (internal only). Players keep their own RPCN account, for example on the official server | 127.0.0.1:31313 |

The images contain no game files and no CCP code. The game, firmware and license are provided as a data folder
on the server.

---

## 1. Server setup with Docker

### 1.1 Requirements

- **Server:** Linux, x86-64 with AVX2. Plan on at least 8 CPU cores and 16 GB RAM. A running host uses about
  7 cores, because RPCS3 emulates the PS3's six SPUs on separate threads. No GPU is needed.
- **Software:** Docker Engine with Compose v2 (`docker compose`). Windows or macOS with Docker Desktop works too,
  see 1.6.
- **Disk:** about 15 GB (game data ~3 GB, RPCS3 build ~5 GB, caches).
- **A Windows PC with a working local installation** of DUST 514 in RPCS3, prepared as described in the
  repository's `README.md` (game 03.19, patched `COMMON.SDAT`, EdgeZlib patch, extracted client modules in
  `research\extracted_0319`). The data folder for the server is exported from it.

### 1.2 Create the data folder (on the Windows PC)

The export collects everything the server needs: the game with our client patch, the license, the firmware,
the game patches, a Null-renderer configuration and the extracted client modules for the `catma` service.

```powershell
tools\export_host_data.ps1 -Out E:\dust514-data
```

- On the first run the script writes an `rpcn.yml` for the host account `DustHost` with a random password
  (`-RpcnNpid` picks another name). The account lives on the stack's own RPCN server, and the watchdog creates it
  there on the first start.

- In the copied game folder,
  `rpcs3/config/rpcs3/dev_hdd0/game/NPUB30643/USRDIR/DUSTGAME/SAKE.INI` must point to the server itself:
  `url = http://127.0.0.1:8080`. This is the default of the local setup.

Upload the folder to the server, for example to `/srv/dust514-data`:

```bash
rsync -a E:/dust514-data/ user@server:/srv/dust514-data/
```

### 1.3 Configure

```bash
git clone <this repository> dust514srv
cd dust514srv/docker
cp .env.example .env
```

Edit `.env`:

| Setting | Meaning |
|---|---|
| `DUST_DATA` | Path of the data folder, e.g. `/srv/dust514-data` |
| `ADMIN_TOKEN` | Password for the web admin; use a long random value on a public server |
| `CREST_PORTS` | Backend ports, default `80,443,8080` |
| `HOST_GAME_ARGS` | Auto-login of the host; keep the default |
| `BUILD_JOBS` | Parallel compile jobs for RPCS3; 0 = all cores. Lower it if the build runs out of memory |

### 1.4 Build and start

```bash
docker compose up -d --build
docker compose logs -f host
```

- The first build compiles RPCS3 and takes 10–40 minutes, depending on the CPU.
- The host's first start compiles the game's PPU/SPU code: about 4 minutes until the battle map is up. Later
  starts take about 100 seconds.
- `docker compose ps` should show `host`, `crest` and `catma` as running.
- The host logs in, enters the merc quarters and starts the battle map from the web admin's settings (Ambush by
  default). From then on it is listed in the battle finder.

### 1.5 Network and firewall

Open these ports to the players:

| Port | Protocol | Purpose |
|---|---|---|
| 7777 | UDP | Battle (UE3 listen server) |
| 8080 | TCP | Backend (CREST API) |
| 80, 443 | TCP | Backend under the original CCP host names |
| 8088 | TCP | Web admin: **do not open publicly**; use an SSH tunnel or a TLS reverse proxy instead |

Players connect to the address that the battle finder hands out. Set it to the server's **public address**: web
admin → *Battle host* → address for clients (stored as `target_listen` in `dust_server/fake_battle.json`). The
default `127.0.0.1` only works for clients on the server itself.

Access the web admin through an SSH tunnel:

```bash
ssh -L 8088:127.0.0.1:8088 user@server
# then open http://127.0.0.1:8088/ in the browser
```

### 1.6 Web admin

Open `http://<server>:8088/` and log in with `ADMIN_TOKEN`. Without a token in `.env`, the server generates one on
the first start and stores it in `dust_server/state/admin_token.txt`.

- **Status:** whether the host is online, the running map, battle members, recent requests.
- **Battle host:** level, game mode, terraform, lighting, battle name, teams, address for clients.
  - Changing the **game mode** needs a host restart: *Restart host* (the running game crashes when it switches
    modes in place).
  - Changes within the same mode are applied with *Save & apply*.
- **News & documents, ISK market, AUR store, loyalty stores, login rewards, wallet:** content the clients load at
  login. Purchases are not saved yet.

### 1.7 Operation

- **Watchdog:** restarts RPCS3 when it exits, hangs, or the game stops talking to the backend.
- **Restart the host by hand:** `touch $DUST_DATA/rpcs3/control/restart`, or use *Restart host* in the web
  admin.
- **Stop the host:** `touch $DUST_DATA/rpcs3/control/stop`. It stays stopped until the file is removed.
- **Status of the host:** `$DUST_DATA/rpcs3/control/status.json`.
- **Logs:**
  - RPCS3: `$DUST_DATA/rpcs3/cache/rpcs3/RPCS3.log`
  - Backend: `dust_server/logs/requests.jsonl`
  - Game log of the host: `dust_server/logs/client.log`
- **After an update of the repository:** `docker compose up -d --build`. RPCS3 is only recompiled when its
  version or a patch changes.

### 1.8 Docker Desktop (Windows/macOS)

Docker Desktop's host networking does not route UDP replies back, so players would get no answer from the
battle. Use the override file, which publishes the ports instead:

```bash
docker compose -f compose.yaml -f compose.desktop.yaml up -d --build
```

In this mode all containers share the `host` container's network. If you recreate `host`, recreate `crest`
and `catma` as well (`docker compose -f compose.yaml -f compose.desktop.yaml up -d --force-recreate`).

---

## 2. Client setup (the game in RPCS3)

Each player needs a PC that runs DUST 514 in RPCS3 (Windows or Linux, a GPU with Vulkan).

### 2.1 Install RPCS3, firmware and the game

1. Install [RPCS3](https://rpcs3.net) and the PS3 firmware (*File → Install Firmware*).
2. Install DUST 514 (NPUB30643): the base game plus updates **03.18 and 03.19** (*File → Install Packages*), and the
   license file `UP5018-NPUB30643_00-DUST514EVEONLINE.rap` (dropped onto RPCS3, or copied to
   `dev_hdd0/home/00000001/exdata/`).
3. Add the **EdgeZlib patch** for 03.19 (`PPU-ae3f946dfcb103b782f73f1cc5f90587e652f439`, "Force PPU zlib fallback")
   from [514_CROP-DUSTInG](https://github.com/ProtoDroidBot/514_CROP-DUSTInG) to RPCS3's `patches` folder and
   enable it in the patch manager. Without it the game stays on a black screen after the intro.

### 2.2 RPCN account

Every player needs their own RPCN account: *Configuration → RPCN*, create the account and log in. The game
needs a PSN connection to start, and RPCN provides it. The official RPCN server is fine; it does not have to be
the one the battle host uses.

### 2.3 Game configuration in RPCS3

Right-click DUST 514 → *Create Custom Configuration* (or *Change Custom Configuration*):

| Tab | Setting | Value |
|---|---|---|
| Network | Network Status | Connected |
| Network | PSN Status | RPCN |
| Network | IP/Hosts switches | `crest.eveonline.com=<server>&&dust.dyn.ccpgamescdn.com=<server>` |
| GPU | Renderer | Vulkan |
| Advanced | Write Color Buffers | on (fixes lighting artifacts) |
| Advanced | Read Depth Buffer, Write Depth Buffer | on (clouds, fog and glow no longer cover the scene) |

Replace `<server>` with the server's IP address. For a server on the same PC that's `127.0.0.1`.

### 2.4 Point the game at the server

In the game folder `dev_hdd0/game/NPUB30643/USRDIR/DUSTGAME/`, make a backup of `SAKE.INI` and set:

```ini
url = http://<server>:8080
```

`SAKE.INI` is not listed in the game's file table (`PS3TOC.TXT`), so nothing else has to change after editing it.

Optional (the tools are in the repository's `tools/` folder and read the game folder from `DUST_GAME_DIR`,
default `D:\rpcs3\dev_hdd0\game\NPUB30643\USRDIR\DUSTGAME`):
- **Skip the intro movie:** copy `MOVIES/EMPTY.BIK` over `MOVIES/INTRO.BIK`, then run
  `python tools/set_toc_size.py Movies/Intro.bik`.
- **Send the game's log to the server** (helps with debugging): `python tools/patch_common_sdat.py`, then
  `python tools/set_toc_size.py COMMON.SDAT`. Undo with `python tools/patch_common_sdat.py --restore`.
  The patch sends to `127.0.0.1:8514`, so this only helps when the server runs on the same PC.

### 2.5 Play

1. Start DUST 514 in RPCS3. The game logs in through the server, then you choose a character and land in the
   merc quarters.
2. Open the **battle finder**. The server's battle is listed under the name set in the web admin (default
   `LocalTest`). Join it.
3. The game loads the battle map from the host. Pick a spawn point on the deploy map, or use *Smart Deploy*.

Starting without key presses (useful for tests):

```bash
rpcs3 --no-gui <path to EBOOT.BIN> -- -autologinserver=<server>:8080 -autologincharindex=0 -autologinbattle=LocalTest
```

### 2.6 Troubleshooting

| Problem | Cause / fix |
|---|---|
| "Connection to PlayStation Network was lost" right at start | RPCN not logged in, or the account is in use elsewhere (one login per account) |
| Black screen after the intro | EdgeZlib patch missing or not enabled |
| Login fails / server not available | `SAKE.INI` url or the IP/Hosts switches don't point to the server, or TCP 8080/80/443 are blocked |
| Battle not listed in the battle finder | Host not running yet: check *Status* in the web admin or `docker compose logs host` |
| "Your connection to the host has been lost" | UDP 7777 is not reachable from the client, or the battle finder hands out the wrong address (web admin → *Battle host*) |
| Light streaks and banding on the map | Turn on *Write Color Buffers* |
| Cloud layer or a blue glow drawn in front of everything | Turn on *Read Depth Buffer* and *Write Depth Buffer* |
| Flickering white dashes on lit floors | Known RPCS3 issue, no setting fixes it yet (see below) |

## Current limitations

- White dashes flicker on lit floors and move with the camera. None of these RPCS3 settings helped: Handle RSX
  Memory Tiling, Strict Texture Flushing, Shader Precision Ultra (large FPS loss), SPU XFloat Accurate, Strict
  Rendering Mode. Accurate RSX reservation access together with Accurate SPU DMA crashes the game in the merc
  quarters, and with OpenGL the game crashed when joining the battle.
- Tested with two players: the host plus one client. More players and long sessions are untested.
- All players use CCP's offline characters. Purchases and progress are not saved yet.
- Switching the game mode needs a host restart (about 100 seconds), and players have to rejoin.
- Game modes: Ambush, Skirmish and Domination work. In Acquisition the spawn point is in a red zone, and Planetary
  Conquest is not available.
