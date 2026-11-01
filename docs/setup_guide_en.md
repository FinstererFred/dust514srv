# DUST 514 revival – setup guide

How to go from your own DUST 514 package files to a running battle server, and how players connect to it with
the PS3 client in RPCS3. This is a private, experimental project, not affiliated with CCP Games or Sony. You need
your own copy of the game, its license and the PS3 firmware; none of them is distributed here.

Contents:
1. [Prepare the game (Windows PC)](#1-prepare-the-game-windows-pc)
2. [Server setup with Docker](#2-server-setup-with-docker)
3. [Client setup (players)](#3-client-setup-players)

## How it works

DUST 514 battles originally ran on CCP's own battle servers, which were never released. This project hosts a
battle on a PS3 client instead: an RPCS3 instance on the server runs the game as an Unreal Engine 3
**listen server** (no GPU needed, it renders nothing). Next to it run our replacement for CCP's backend
(CREST API, battle finder, web admin) and a service that answers game data requests from the client's own
database.

| Container | Purpose | Ports |
|---|---|---|
| `host` | RPCS3 (built from source) running the battle map, plus a watchdog that restarts it | UDP 7777 |
| `crest` | Backend for all clients (CREST API, battle finder) and the web admin | TCP 8080, 80, 443; TCP 8088 (admin) |
| `catma` | Game data service (internal only) | 127.0.0.1:8090 |
| `rpcn` | RPCN server the host signs in to (internal only). Players keep their own RPCN account, for example on the official server | 127.0.0.1:31313 |

The images contain no game files and no CCP code. The game, firmware and license go into a **data folder** that
you build on a Windows PC from your own installation and copy to the server.

### Overview

| Step | Where | Result |
|---|---|---|
| 1.1–1.3 | Windows PC | DUST 514 03.19 installed from the PKG files in RPCS3, with license, firmware and EdgeZlib patch |
| 1.4–1.5 | Windows PC | Data folder (~3 GB) with a host copy of the game, exported by `tools\export_host_data.ps1` |
| 2.1–2.4 | Linux server | Data folder uploaded, Docker stack built and started |
| 2.5–2.6 | Linux server | Ports open, battle address set in the web admin: the battle is listed in the battle finder |
| 3 | Each player's PC | RPCS3 client pointed at the server |

The Windows PC from step 1 can also be your own client for step 3: the export changes only the copy in the data
folder, not the installation it comes from.

### What you need

- **Game files from your own PS3 / PSN account:**
  - the DUST 514 package (`.pkg`, title ID **NPUB30643**) and its update packages up to version **03.19**
  - the license file `UP5018-NPUB30643_00-DUST514EVEONLINE.rap`
- **PS3 firmware** `PS3UPDAT.PUP`, downloaded from PlayStation's official system software page.
- **EdgeZlib patch** for 03.19 from [514_CROP-DUSTInG](https://github.com/ProtoDroidBot/514_CROP-DUSTInG) (without it
  the game hangs on a black screen after the intro).
- **Windows PC** (step 1): [RPCS3](https://rpcs3.net), [Git](https://git-scm.com), Python 3 (as `python` in the
  `PATH`) and [Miniconda](https://docs.conda.io/en/latest/miniconda.html) for a Python 2.7 environment.
- **Linux server** (step 2): x86-64 with AVX2, at least 8 cores and 16 GB RAM, about 15 GB disk, Docker Engine with
  Compose v2. No GPU.

---

## 1. Prepare the game (Windows PC)

### 1.1 Install RPCS3, firmware and the game

1. Download RPCS3 from [rpcs3.net](https://rpcs3.net) and unpack it, e.g. to `C:\rpcs3`. The RPCS3 version of this PC
   does not matter for the server (the Docker image builds its own), but if you also play on it, see the version
   note in 3.1.
2. *File → Install Firmware* → `PS3UPDAT.PUP`.
3. *File → Install Packages/Raps/Edats* → the DUST 514 package, then the update packages in ascending order up to
   03.19. RPCS3 installs them to `dev_hdd0\game\NPUB30643\`.
4. Install the license the same way (or drop the `.rap` file onto the RPCS3 window). It ends up in
   `dev_hdd0\home\00000001\exdata\`.
5. Check: the game list shows DUST 514 with version **03.19**. All host patches are written for 03.19.

### 1.2 EdgeZlib patch

Put the EdgeZlib patch from 514_CROP-DUSTInG into RPCS3's `patches` folder as `NPUB30643_patch.yml` (or import it in
*Manage → Game Patches*), then enable "Force PPU zlib fallback (EdgeZlib bypass)" for 03.19 there
(`PPU-ae3f946dfcb103b782f73f1cc5f90587e652f439`). The export copies the folder to the host. Don't put it into
`patch.yml`: the export replaces that file with the host patches.

Optional check: start the game. It should play the intro and reach its login screen (the login itself fails until
the server runs).

### 1.3 Repository and Python 2.7

All commands in steps 1.3 and 1.4 are meant for **Windows PowerShell** (Start menu → "Windows PowerShell"), not for
the old command prompt (`cmd.exe`).

```powershell
git clone <this repository> C:\dust514srv
cd C:\dust514srv
conda create -p tools\py27 python=2.7
```

**What conda is for:** DUST 514 runs Python 2.7 inside the game, and its Python cannot compile source files. The
export therefore compiles our client patch (`client_patch\*.py`: dev hook and log forwarding for the host) to Python 2.7
bytecode before it adds it to the game's `COMMON.SDAT`. Python 2.7 is long out of support and hard to install next to a
current Python, so conda creates a separate Python 2.7 just for this, in the folder `tools\py27` where the export looks
for it. It changes nothing else on the PC. The server does not need it: the Docker images bring their own Python.

If `conda` is not found in PowerShell, run the `conda create` line in the "Anaconda Prompt" from the Start menu instead
(after `cd C:\dust514srv`), or run `conda init powershell` once and open a new PowerShell window.

### 1.4 Export the data folder

In PowerShell, in the repository folder:

```powershell
cd C:\dust514srv
powershell -ExecutionPolicy Bypass -File tools\export_host_data.ps1 -Rpcs3 C:\rpcs3 -Out E:\dust514-data
```

`-ExecutionPolicy Bypass` allows this one script to run: Windows blocks unsigned PowerShell scripts by default
("running scripts is disabled on this system"). It does not change the setting for other scripts.

`-Rpcs3` is the RPCS3 folder from 1.1 (default `D:\rpcs3`), `-Out` an empty folder with about 4 GB free space.
The script copies the game, license, firmware and patches and then prepares the copy for the host:

| What | Why |
|---|---|
| `COMMON.SDAT` with `client_patch/` (size updated in `PS3TOC.TXT`) | Dev hook: the backend drives the host (log in, start the battle map, match end), and the game's log is forwarded |
| `COOKEDPS3/DUSTGAME.XXX` with the data log patch | The host follows who holds the objectives (MCC barrage in Skirmish) |
| `SAKE.INI`: `url = http://127.0.0.1:8080` | The host talks to the backend on the same server |
| `patches/patch.yml` + `patch_config.yml` | Host-only game patches from `rpcs3_patches/`: all outpost LODs and collision far from the host, no world rendering (about +65 % server tick), vehicle requests |
| `custom_configs/config_NPUB30643.yml` | RPCS3 config of the host from `docker/host/config_NPUB30643.yml`: Null renderer, no audio, RPCS3 thread scheduler, IP switches to 127.0.0.1 |
| `rpcn.yml` | Host account `DustHost` with a random password on the stack's own RPCN server (created on the first run only; `-RpcnNpid` picks another name). The watchdog creates the account on the first start |
| `extracted_0319/COMMON`, `/PYTHON` | The game's Python modules, unpacked from the original `COMMON.SDAT` and `PYTHON.SDAT`, for the `catma` service |

The originals stay next to the patched files as `*.orig`, and every run patches from them, so you can run the
export again at any time (for example after an update of the repository). It ends with
`data folder ready: E:\dust514-data (3,1 GB)`.

Never use the exported game folder as a client: the host patches turn off world rendering.

### 1.5 Upload

Copy the whole folder to the server, for example to `/srv/dust514-data`:

```bash
rsync -a E:/dust514-data/ user@server:/srv/dust514-data/
```

The data folder holds your game, license and firmware: keep it private and do not share it.

---

## 2. Server setup with Docker

### 2.1 Configure

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
| `CHAR_STORE` | `1` (default): every player's RPCN account gets its own characters, saved on the server. `0`: everyone plays CCP's three offline characters, nothing is saved |
| `HOST_ACCOUNTS` | RPCN name of the host account (`NPID` in the data folder's `rpcn.yml`, default `DustHost`). The host always plays a shared stand-in character |

### 2.2 Build and start

```bash
docker compose up -d --build
docker compose logs -f host
```

- The first build compiles RPCS3 from source (the version is pinned in `docker/host/Dockerfile`) and takes
  10–40 minutes, depending on the CPU.
- The host's first start compiles the game's PPU/SPU code: about 4 minutes until the battle map is up. Later
  starts take about 100 seconds.
- `docker compose ps` should show `host`, `crest`, `catma` and `rpcn` as running.
- The host logs in, enters the merc quarters and starts the battle map from the web admin's settings (Ambush by
  default). From then on it is listed in the battle finder.

### 2.3 Network and firewall

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

### 2.4 Web admin

Open `http://<server>:8088/` and log in with `ADMIN_TOKEN`. Without a token in `.env`, the server generates one on
the first start and stores it in `dust_server/state/admin_token.txt`.

- **Status:** whether the host is online, the running map, battle members, recent requests.
- **Battle host:** level, game mode, terraform, lighting, battle name, teams, address for clients.
  - Changing the **game mode** needs a host restart: *Restart host* (the running game crashes when it switches
    modes in place).
  - Changes within the same mode are applied with *Save & apply*.
- **News & documents, ISK market, AUR store, loyalty stores, login rewards, wallet:** content the clients load at
  login.

### 2.5 Operation

- **Watchdog:** restarts RPCS3 when it exits, hangs, or the game stops talking to the backend.
- **Restart the host by hand:** `touch $DUST_DATA/rpcs3/control/restart`, or use *Restart host* in the web
  admin.
- **Stop the host:** `touch $DUST_DATA/rpcs3/control/stop`. It stays stopped until the file is removed.
- **Status of the host:** `$DUST_DATA/rpcs3/control/status.json`.
- **Logs:**
  - RPCS3: `$DUST_DATA/rpcs3/cache/rpcs3/RPCS3.log`
  - Backend: `dust_server/logs/requests.jsonl`
  - Game log of the host: `dust_server/logs/client.log`
- **After an update of the repository:** `git pull`, run the export (1.4) again if `client_patch/`,
  `rpcs3_patches/` or `docker/host/config_NPUB30643.yml` changed and upload the folder, then
  `docker compose up -d --build`. RPCS3 is only recompiled when its pinned version changes; after that the host
  compiles its PPU/SPU caches once more (first start about 4 minutes).

### 2.6 Docker Desktop (Windows/macOS)

Docker Desktop's host networking does not route UDP replies back, so players would get no answer from the
battle. Use the override file, which publishes the ports instead:

```bash
docker compose -f compose.yaml -f compose.desktop.yaml up -d --build
```

In this mode all containers share the `host` container's network. If you recreate `host`, recreate the other
services as well (`docker compose -f compose.yaml -f compose.desktop.yaml up -d --force-recreate`).

---

## 3. Client setup (players)

Each player needs a PC that runs DUST 514 in RPCS3 (Windows or Linux, a GPU with Vulkan).

### 3.1 Install RPCS3, firmware and the game

1. Install [RPCS3](https://rpcs3.net) and the PS3 firmware (*File → Install Firmware*).
   **RPCS3 version:** builds from 0.0.43-20550 (31 October 2026) on hang DUST 514 on a black screen at start. Use
   0.0.43-20549 or older (older builds are listed on RPCS3's GitHub releases), and decline RPCS3's update prompt at
   startup until a newer build is confirmed to work.
2. Install DUST 514 (NPUB30643): the game package plus the updates up to **03.19** (*File → Install Packages*), and
   the license file `UP5018-NPUB30643_00-DUST514EVEONLINE.rap` (dropped onto RPCS3, or copied to
   `dev_hdd0/home/00000001/exdata/`).
3. Add the **EdgeZlib patch** as in 1.2. Do not add the host patches from `rpcs3_patches/` to a client.

### 3.2 RPCN account

Every player needs their own RPCN account: *Configuration → RPCN*, create the account and log in. The game
needs a PSN connection to start, and RPCN provides it. The official RPCN server is fine; it does not have to be
the one the battle host uses.

### 3.3 Game configuration in RPCS3

Right-click DUST 514 → *Create Custom Configuration* (or *Change Custom Configuration*):

| Tab | Setting | Value |
|---|---|---|
| Network | Network Status | Connected |
| Network | PSN Status | RPCN |
| Network | IP/Hosts switches | `crest.eveonline.com=<server>&&dust.dyn.ccpgamescdn.com=<server>` |
| Network | Bind address | `0.0.0.0` (the default) |
| GPU | Renderer | Vulkan |
| Advanced | Write Color Buffers | on (fixes lighting artifacts) |
| Advanced | Read Depth Buffer, Write Depth Buffer | on (clouds, fog and glow no longer cover the scene) |

Replace `<server>` with the server's IP address. For a server on the same PC that's `127.0.0.1`.

### 3.4 Point the game at the server

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

### 3.5 Play

1. Start DUST 514 in RPCS3. The game logs in through the server. On the first login of an RPCN account the character
   list is empty: create a character (race, bloodline, portrait, name). Then choose it and you land in the merc
   quarters.
2. Open the **battle finder**. The server's battle is listed under the name set in the web admin (default
   `LocalTest`). Join it.
3. The game loads the battle map from the host. Pick a spawn point on the deploy map, or use *Smart Deploy*.

Starting without key presses (useful for tests):

```bash
rpcs3 --no-gui <path to EBOOT.BIN> -- -autologinserver=<server>:8080 -autologincharindex=0 -autologinbattle=LocalTest
```

### 3.6 Troubleshooting

| Problem | Cause / fix |
|---|---|
| Export: `tools\py27 is missing` | Create the Python 2.7 environment (1.3) |
| Export: "running scripts is disabled on this system" | Start the export with `powershell -ExecutionPolicy Bypass -File …` as shown in 1.4 |
| Export: `python` is not recognized | Install Python 3 and tick "Add python.exe to PATH" in the installer, then open a new PowerShell window |
| Export: `DUST 514 (NPUB30643) is not installed` | `-Rpcs3` does not point to the RPCS3 folder with the installed game |
| Host stays `waiting` in `status.json` | The `rpcn` container is not running; `docker compose logs rpcn` |
| Host never reaches the battle map | `$DUST_DATA/rpcs3/cache/rpcs3/RPCS3.log`: game version must be 03.19, "Applied patch" lines for the EdgeZlib and host patches |
| "Connection to PlayStation Network was lost" right at start | RPCN not logged in, or the account is in use elsewhere (one login per account). Also check *Network → Bind address*: it must be `0.0.0.0` (or a real address of the PC); a loopback address like `127.0.0.2` cannot reach the RPCN server |
| Black screen after the intro | EdgeZlib patch missing or not enabled |
| Black screen, the window title shows less than 1 FPS | RPCS3 0.0.43-20550 or newer: go back to 0.0.43-20549 (3.1) |
| Login fails / server not available | `SAKE.INI` url or the IP/Hosts switches don't point to the server, or TCP 8080/80/443 are blocked |
| Battle not listed in the battle finder | Host not running yet: check *Status* in the web admin or `docker compose logs host` |
| "Your connection to the host has been lost" | UDP 7777 is not reachable from the client, or the battle finder hands out the wrong address (web admin → *Battle host*) |
| Light streaks and banding on the map | Turn on *Write Color Buffers* |
| Cloud layer or a blue glow drawn in front of everything | Turn on *Read Depth Buffer* and *Write Depth Buffer* |
| Flickering white dashes on lit floors | Known RPCS3 issue, no setting fixes it yet (see below) |

## Current limitations

- Tested with up to five players (the host plus four RPCS3 clients). The host itself was also measured with 32
  simulated clients that move and fire (about 20 server ticks per second); real matches with more than five players
  are untested.
- There are no bots: the release build of the game has no AI spawning. Every opponent is a player.
- Characters are saved per RPCN account in `dust_server/state/dust.sqlite` (skills, skill points, inventory, fittings,
  ISK, match rewards). Back up that file. The server knows players only by their RPCN name, so a lost RPCN account
  means lost characters. It accepts a login only with a ticket signed by the official RPCN server (np.rpcs3.net), so
  nobody can log in under someone else's RPCN name. Players on another RPCN server cannot log in unless that server
  signs its tickets and the operator adds its public key (`DUST_TICKET_KEYS`, see `docker/README.md`).
- The backend runs plain HTTP. A login ticket stays valid for about 15 minutes after it was issued, plus one hour of
  tolerance, so do not run the backend over networks you do not trust.
- Switching the game mode needs a host restart (about 100 seconds), and players have to rejoin.
- Game modes: Ambush, Skirmish and Domination work. In Acquisition the spawn point is in a red zone, Ambush OMS is
  untested, and Planetary Conquest is not available.
- Requested vehicles appear next to the player instead of being dropped from orbit.
- White dashes flicker on lit floors and move with the camera. None of these RPCS3 settings helped: Handle RSX
  Memory Tiling, Strict Texture Flushing, Shader Precision Ultra (large FPS loss), SPU XFloat Accurate, Strict
  Rendering Mode. Accurate RSX reservation access together with Accurate SPU DMA crashes the game in the merc
  quarters, and with OpenGL the game crashed when joining the battle.
