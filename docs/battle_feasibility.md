# DUST 514: Gefechte im wiederbelebten Client (Kompaktstand)

Stand 2026-10-27 (nach Test 6). Client 03.19, Build 2.13.0.249 `DUST-ALPHA`. Dekompilierter Python-Code unter
`research\decompiled_0319\COMMON` (Zeilennummern beziehen sich darauf).
Die ausführliche Fassung mit allen Experimenten liegt als `docs/archive/battle_feasibility_full.md`. Sie muss nicht
bei jeder Session gelesen werden. Bei Bedarf gezielt nach den Stichworten in Klammern suchen.

## 1. Kurzfassung

- Der Gefechtsserver bei CCP war derselbe UE3-Code mit demselben Python, nur als Dedicated Server
  (`GIsServer and not GIsClient`) und als **Windows-Build** (Cook-INI `Client=WinDrv.WindowsClient`). Nicht veröffentlicht.
- Der PS3-Client enthält einen Offline-Modus, der alle Gefechtsserver-Dienste im Client-Prozess startet. Alle Karten
  liegen lokal vor.
- **Entscheidung: Listen-Server (RPCS3-Host) mit gezielten RPCS3-Patches.** Ein echter Dedicated-Pfad im PS3-Binary
  ist unwahrscheinlich, ein Nachbau des Servers wäre ein Mannjahre-Projekt (UE3-Replikation aller DustGame-Klassen).
- **Läuft:** Host plus Client 2 (zweite RPCS3-Instanz). Ambush, Skirmish, Domination mit zwei Spielern. Beitritt über die
  Gefechtssuche, Credentials vergibt der CREST-Server. Host ohne GPU im Docker (Null-Renderer mit eigenem RPCS3-Patch).
  Kollision fern vom Host gelöst (Patch 0.5, Test 6).
- **Offen:** Skalierung auf viele Spieler (nur 2 getestet), Speicher und FPS bei voller Belegung, Matchende und
  Belohnungen, einige Modi (siehe Abschnitt 9).
- **Keine Bots:** Im Release-Build ist die gesamte KI-Spawn-Logik zu leeren Stubs herauskompiliert. Gegner gibt es nur
  über Mehrspieler.

## 2. Ablauf im Client (vom Menü bis zur Verbindung)

Dienste: `uiSvcBattle` (Gefechtssuche), `battleClient3` (CREST-Abfragen, Beitritt, Backend-Meldungen), `pingClient`,
`dustClient` (Server bereit, Ergebnisse), `dustUnreal` (setzt `CleanLoad` ab), `spawnClient`.

1. Gefechtssuche pollt alle 15 s `battleTheatres`, `battleQueues`, `battles` (CREST).
2. Beitritt: `POST battle['members']['href']` mit `vnd.ccp.eve.BattleMemberCreate-v1`
   (`{"character": {"href"}, "team"?, "region"?}`), Antwort `BattleMember-v1`. Gefecht ist beitretbar ab `status >= 3`.
3. Backend schickt über den Notification-Stream `OnBattleMemberJoined`, dann `OnBattleMemberConnect`.
4. Client führt aus:
   `CleanLoad <adresse>:<port>?credential=…?Team=…?LightingMode=…?DefaultArmor=…` (`dustUnreal` Z. 69).

Notification-Stream: Zeile `{"sn": n, "data": {"contentType": "...OnBattleMemberConnect-v1", "body": {...}}}`.

| Name | Pflichtfelder im Body |
|---|---|
| `OnBattleMemberJoined` | `href`, `character.href`, `battle.href` |
| `OnBattleMemberConnect` | `href`, `server.address`, `server.port`, `credential`, `team` (`attacker`=0, `defender`=1), `battle.id`, `battle.href` |
| `OnBattleMemberLeft` | `href` |
| `OnBattleQueueJoined/Left`, `OnBattleTerminated` | siehe Code (`battleClient3.StartProcess`) |

Battle-Objekt (`Battle-v1`): braucht u. a. `href`, `id`, `name`, `status`, `teamSelect`, `attacker/defender`,
`region/constellation/system/planet`, `mode.id` **und `mode.name`** (fehlt es, bricht `overviewPanel` mit `KeyError` ab),
`members.href`.

Wichtig: `CleanLoad` ist **kein** allgemeines `open`. Für einen lokalen Kartenstart braucht man `Start <map>?…`
(siehe Abschnitt 4). Nach einem gescheiterten `CleanLoad` hängt das Laden der Söldnerunterkunft, dann Neustart.
Verbindung ist UE3-UDP auf Port 7777, `InitialConnectTimeout=60`.

## 3. So arbeitete CCPs Gefechtsserver (`dust/battleServer.py`)

1. Start mit `launchconfig=<ini>` (Abschnitte `[server]`, `[battle]`, `[mapurl]`, `[sockets]`).
2. OAuth-Login mit `scope battleserver`, Status `starting`, Gefecht und Mitglieder vom Backend holen.
3. Pro Mitglied zufällige 24-stellige `credential`, per `PUT member {"team","credential"}` ans Backend. Das Backend
   leitet sie als `OnBattleMemberConnect` an den Client. UE3 ordnet den Client über
   `GetDustCharacterURIFromCredential` dem Charakter zu.
4. Ende: `POST battle['completed']` mit Gewinner, Kriegspunkten, Verbrauch. Server beendet sich nach 120 s.
5. Auf dem Listen-Server fragt `DustServerConfig` die `[sockets]`-Belegung nicht ab (nur bei `NetMode == Dedicated`).
   Mit `loadDefaultOutpost` gilt die Vorgabe des Karteneditors. Kleine und mittlere Sockel bleiben ggf. leer.

Offline-Modus: `userClient.OfflineConnect` → `_InitBattleServices` (lädt `startmini.GetBattleServices`),
`userBattle.OfflineConnect` legt 100 Offline-Charaktere ab ID 2100001611 an (alle Items 999x, Skills Stufe 5).

## 4. Funktionierendes Host-Rezept

Start im Host (steht in `dust_server/dev_commands.json`):

```
Start MN_Craters01?gametype=gamemode_ambush_32p?gameModeLevel=MN_Craters01_BG01_AmbA?bfid=365271?loadDefaultOutpost?Terraform=Desert01?LightingMode=MOOD_DAY?Team=0?Name=DustPlayer?listen?battleID=514001?credential=<Host>
```

- Vorher: Gefechtsdienste starten (`init_battle_services`, `offline_battle_connect`), `userClient.offlineConnectFinished = True`,
  `mark_in_battle`.
- `bfid` = Typ-ID des `GalaxyLevel`, `gameModeLevel` = `mapName` aus dessen `gameModes`. Ohne beides keine Spawnpunkte.
- `Terraform=` liefert das Gelände (`mega=` ist nicht nötig).
- `?battleID=` setzt `mSessionServerID` und schaltet `DustTeamGame.Login` auf den Credential-Zweig. Nur so bekommt jeder
  Spieler eine eigene Charakter-ID. Ohne das bekommen alle die Offline-ID des Host-Prozesses (Kollision, Spawn-Bestätigungen
  gehen an den falschen Spieler).
- `PauseStageTimer` hält den Missions-Timer an (sonst Ende nach ca. 16 min).
- `?PlayerControllerClass=DustGame.DustDevPlayerController` gibt Dev-Befehle (`SetCloneReservesForTeam`, `SpawnByType`,
  `TeleportToSpawnPoint`, …). `DustCheatManager` ist im Release-Build nicht erreichbar.
- Ambush hat keine festen Spawnpunkte: Smart Deploy (Triangle) oder Drop Uplinks.
- Start-Argumente an RPCS3: nur hinter der EBOOT nach `--` (`rpcs3.exe --no-gui EBOOT.BIN -- -autologin…`).

## 5. Mehrspieler-Ablauf

- CREST-Server (`dust_server/crest_app.py`, `fake_battle.json`, Variante `listen`): Beim `POST /battles/514001/members/`
  vergibt er je Spieler Credential, Charakter-ID (ab `first_member_id` 2100001612), URI `/battlecharacters/<id>/` und Team
  (`listen_team`). Dann `OnBattleMemberJoined`, nach 8 s `OnBattleMemberConnect` mit Host-Adresse und UDP 7777.
- Host pollt `GET /dev/battle/members/` alle 3 s und registriert jede neue Credential per Dev-Hook `battle_member`
  (legt `BattleCharacterCache` an). `OnBattleMemberConnect` geht erst raus, wenn der Host die Liste abgeholt hat.
  Ein Client, der mitten ins Kartenladen des Hosts verbindet, bringt den Host zum Absturz.
- Deploy-Karte des Hosts schließt sich, wenn ein fremder Spieler spawnt. Der Dev-Hook öffnet sie nach 6 s wieder
  (`uiSvcOverviewMap.OnRequestOpenMenu(1)`), beobachtet 30 s.
- Autologin ohne Tastendruck: `-autologinserver=<CREST>`, `-autologincharindex=<n>`, `-autologinbattle=LocalTest`
  (Client, nicht Host, sonst tritt der Host seinem eigenen Gefecht bei).
- Zweite RPCS3-Instanz auf demselben PC: eigenes RPCN-Konto nötig (lokaler RPCN-Server `research/rpcn/rpcn.exe`, `127.0.0.1:31313`),
  Bind-Adresse `127.0.0.2` (sonst Portkonflikt UDP 3658), eigener CREST-Port (8081), Probe-Logger auf 17777 statt 7777.
  Auf einem zweiten PC: LAN-Adresse des Hosts eintragen, eigenes RPCN-Konto, kein lokaler RPCN nötig.
- Admin-Weboberfläche (`dust_server/admin.py`, Port 8088): Modus wählen, Host neu starten, News, Markt/Wallet.
  `tools/restart_host.ps1` startet nur den Host neu. Neustart des CREST-Servers trennt laufende Clients.

## 6. Spielmodi und Karten

Quelle: CATMA (`GalaxyLevel.gameModes`, `DustGameType`). Live war eine Kombination bei `mProductionReady` und
`useInMatchmaking` (18 von 33 Levels). Nie live: Testmaps, 48p-Varianten, Craters BG01 `DomA`/`SkA`, Highland BG02 `SkA`,
Ambush OMS auf Highland, SandBox, Valley, ShipInterior. Umschalten mit `dust_server/set_host_mode.py <modus>`.

| Modus | `gametype` | `gameModeLevel` (`bfid`) | Stand |
|---|---|---|---|
| Ambush | `gamemode_ambush_32p` | `MN_Craters01_BG01_AmbA` (365271) | läuft mit 2 Spielern |
| Skirmish | `gamemode_skirmish_4obj_32p` | `…_SkB` (365271) | läuft: MCC, Ziele A–D, je 150 Klone |
| Domination | `gamemode_domination_32p` | `…_DomB` (365271) | läuft: Ziel A, MCC |
| Acquisition | `gamemode_domination_2` | `MN_Highland01_BG01_Dom20A` (365818) | lädt, Spawn in roter Zone, Startposition/Team offen |
| Ambush OMS | `gamemode_ambush_oms_32p` | `…_OmsA` (365271) | ungetestet |
| Planetary Conquest | `gamemode_conquest` | keine Karte | braucht Corps/Bezirke im Backend |

Nicht ausgelieferte Modi: Survival/Drohnen (`gamemode_survival*`): Wellen-Tags fehlen in allen Karten, Match endet nach ca. 21 s
mit „VICTORY“. Die Karte `WB_WARROOM_CA` (Warroom) liegt in den PSARCs.

**Bekannter Absturz:** Moduswechsel im laufenden Host (z. B. Ambush → Skirmish) stürzt wenige Sekunden nach dem Laden ab
(Lesezugriff auf Adresse 0 in `0x8cb534`). Derselbe Modus lässt sich im laufenden Host neu starten. Für einen anderen Modus
Host neu starten.

## 7. RPCS3-Einstellungen (alle Instanzen)

- `Write Color Buffers: true` behebt die Lichtartefakte (RPCS3-Darstellungsfehler).
- **`Read Depth Buffer` und `Write Depth Buffer: true` auf Host und jedem Client.** Terrain-Höhen entstehen auf der GPU und
  werden über den Tiefenpuffer zurückgelesen. Ohne die Einstellung fällt ein Client durchs Terrain. Behebt außerdem Wolkendecke
  und Blau-Leuchten.
- Shader Mode `Async Recompiler (multi-threaded)` (spart die langen Interpreter-Vorkompilierung).
- Nicht verwenden: `Accurate RSX reservation access` + `Accurate SPU DMA` (Absturz in den Merc Quarters), OpenGL (Absturz im Match).
- Ohne Wirkung auf die weißen Striche auf beleuchteten Böden: Tiling, Texture Flushing, Shader Precision Ultra, XFloat, Strict Rendering.
  Fall für RPCS3-Entwickler, zurückgestellt.
- Konfig: `D:\rpcs3\config\custom_configs\config_NPUB30643.yml` (Sicherungen `*.before_*`).

## 8. Host ohne GPU (Null-Renderer, Docker)

- Software-Vulkan (lavapipe) ist unbrauchbar (unter 1 FPS, Absturz).
- **Der Null-Renderer-Hänger ist ein RPCS3-Fehler:** `GSRender::flip()` ruft `rsx::thread::flip(info)` nicht auf, `handle_emu_flip()` schläft
  bei jedem Durchlauf bis zum nächsten 60-Hz-Takt (ein Bild alle 12 s). Fix: eine Zeile, `rpcs3_patches/null-renderer-flip.patch`
  (RPCS3 selbst bauen). Workaround ohne Build: `Frame limit: Off` oder `PS3 Native` (Host flippt dann ständig, RSX-Thread ca. 80 %).
- Docker (`docker/README.md`): RPCS3 aus Quellcode mit Patch, `--headless`, Null-Renderer, `Frame limit: Auto`. Host läuft bis zur
  Karte, Client 2 tritt bei und spawnt. Stolpersteine: Docker-Desktop-Hostnetz leitet keine UDP-Antworten zurück
  (`compose.desktop.yaml`), Neustart des CREST-Servers lässt das Python des Hosts sterben (Watchdog prüft `/dev/host/heartbeat/`).
- Null-Renderer-Host nach 75 s auf der Ambush-Karte, Client 2 mit 26 FPS im Spiel. Bewegung und Kampf über längere Zeit und mehr als
  ein Client sind nicht geprüft.

## 9. Kollision fern vom Host (der zentrale Fund)

**Ursache:** Ein UE3-Listen-Server streamt und berechnet Kollision nur um den Blickpunkt seiner **lokalen Spieler**
(`GEngine+0x474`). Fern davon gilt der grobe Proxy (`X_LOD0_n`) und die grobe Terrain-Kollision. Client 2 sieht die volle Detailstufe,
fällt also beim Host durch die Karte, spawnt in Geometrie oder läuft gegen unsichtbare Wände. Der Dedicated Server hat dafür
vermutlich einen eigenen Pfad (`DAT_01d1d1b8 == 1`, `FUN_0085fef0` setzt dort die LOD-Stufe auf „alle“), den der Listen-Host nicht nimmt.

**Drei Mechanismen, drei Patches** (`rpcs3_patches/host_full_outpost_lod.yml`, im Host unter `patches\NPUB30643_patch.yml`;
nur beim Host aktivieren, Client-Instanz bleibt unverändert):

| Teil | Wo | Was |
|---|---|---|
| Outpost-LOD | `0x85f12c` `lwz r4,0x20(r24)` → `lis r4,0x7fff` (LOD-Manager `FUN_0085ed78`) | Host lädt alle LOD-Stufen aller Outposts (ca. 4,3–4,8 GB RAM) |
| Überblendung Proxy/Detail | Höhle bei `0x99ae94` (in `FUN_0099ac80`) | „Nah“ gilt, wenn irgendein Spieler (PawnList) nah ist, nicht nur der Host-Blickpunkt |
| Terrain-Kollisionskacheln | Höhle bei `0x7fb7bc` (in `FUN_007fb450`, ruft `FUN_008240e8` je Pawn) | Host verfeinert die `MegaTerrainCollisionComponent`-Kacheln um alle Pawns |

Eine dritte Höhle bei `0x820088` (Terrain-Streaming) ist für die Kollision wirkungslos und kann bleiben.
Patch-Typ: RPCS3 `calloc` (Code-Höhle), Zeilen erzeugt `research/tools_local/cave_asm.py`.
Strukturoffsets: `WorldInfo.ControllerList +0x4f4`, `PawnList +0x4f8`, `Pawn.Controller +0x1f4`, `Pawn.NextPawn +0x1f8`,
`Controller.NextController +0x1e4`, `Actor.WorldInfo +0xec`, Pawn-Position `+0x54`, Physik `+0x94`, Base `+0xa0`.

**Verlauf:** 0.1 (LOD-Zeile) → 0.2 (alles „nah“, Nebenwirkung: innere Cluster ausgeblendet) → 0.3 (Höhle Überblendung) →
0.4/0.5 (Höhle Terrain-Kacheln, erst in `FUN_007fb450` wirksam). **Test 6:** Host und Client haben dieselben Kollisionskacheln
(205 bzw. 207), Pawn-Höhe auf beiden Seiten gleich (66778.0 / 66778.4), Absturz keiner, Host 26 FPS, 4,6 GB.

**Noch offen:** gezielte Prüfung der alten Fallstelle (153509, 41800); `FUN_007f9b54`/`FUN_007f7b0c` laufen ebenfalls nur über lokale
Spieler; mehr als 2 Spieler; Speicher und FPS bei voller Belegung. Zurück auf 0.2: beide `calloc`-Blöcke durch die Zeile `0x0099aaf0` ersetzen
(Sicherungen `NPUB30643_patch.yml.before_lod0*`).

## 10. Gemessene Leistung des Hosts (RPCS3)

| Test | FPS Host | RAM |
|---|---|---|
| Test 2 (Patch 0.2) | 12–16 | ca. 4,8 GB |
| Test 4 (Patch 0.3) | 27 | 4,3 GB |
| Test 6 (Patch 0.5) | 26 | 4,6 GB |
| Client 2 (Vulkan) | 26 | ca. 4–4,5 GB |

Alle mit zwei Spielern. Engine-Konfiguration: `NetServerMaxTickRate=30`. Ein UE3-Listen-Server rechnet das Spiel im Takt seines Renderings,
ein Host unter 30 FPS liegt also schon bei 2 Spielern unter dem Ziel-Tick. Es gibt keine Messung mit mehr Spielern.

## 11. Bots und KI

Release-Build: `DustDevPlayerController.ServerSpawnAI`, `DustSvcAutobot.SpawnBots` (leere Stubs `blr` bei `0x20980`),
`DustSkirmishGame.FindAISpawnPoint` und `DustSpawner.AddAI` (`return 0` bei `0x26ec0`). In keiner Karte gibt es `DustAISpawnPoint`.
Passive Drohnen-Nester per `SpawnInstallationByType` greifen nicht an. Bots wären nur per EBOOT-Patch nachrüstbar (nicht machbar).

## 12. Werkzeuge und Pfade (alle unter `research/`, nicht im Repo)

- Ghidra 12.1.4 headless (`research/ghidra/dust514_eboot`, Skript `scripts/DumpDust.java`). Entschlüsselte EBOOT: `research/eboot_0319/`
  (`rpcs3.exe --headless --decrypt <EBOOT.BIN>`).
- `tools_local/`: `live_dump.py` (Abbild des laufenden Prozesses, auch `--no-gui`), `memdump.py`, `streaming_levels.py`, `pawn_state.py`,
  `uobjects.py` (Layout: `+0x28` Outer, `+0x2c` Name, `+0x34` Class, `+0` vtable), `upk.py`, `uscript.py` (UnrealScript-Bytecode),
  `native_table.py` (3578 Native-Einträge, TOC `r2 = 0x1c8a420`), `cave_asm.py`.
- `tools/`: `start_dust.ps1` (Parameter `-Rpcs3`, `-GameArgs`, `-Monitor`, `-OffsetX`), `restart_all.ps1`, `restart_host.ps1`,
  `patch_common_sdat.py` + `set_toc_size.py` (nach Änderungen an `client_patch/` beide Installationen patchen).
- Client-Patches: `client_patch/` (in `COMMON.SDAT`), `dustdevhook.py` pollt `GET /dev/commands/` (Aktionen `ue3`,
  `init_battle_services`, `offline_battle_connect`, `mark_in_battle`, `call`, `sleep`, `battle_member`). Python muss als Bytecode (`marshal`) ankommen.
- Installationen: Host `D:\rpcs3`, Client 2 `D:\rpcs3_b`.

## 13. Fundstellen (Python, dekompiliert)

`dust/battleClient3.py`: `Reload` 78, `JoinQueue` 231, `JoinBattle` 301, `OnBattleMemberJoinedFromBackend` 328, `OnBattleMemberConnectFromBackend` 344,
`UpdateBattle` 356, `-autologinbattle` 373. `dust/dustClient.py`: `InvokeSvcMethodOnBattleServerAsync` 158, `OnBattleMemberConnectNotification` 244.
`dust/dustUnreal.py`: `OnProceedBattleConnectNotification`/`CleanLoad` 69–70. `dust/battleServer.py`: `OnDustUserLogonNotification` 163, `_LoginToBackend` 204,
`_CompleteBattle` 223, `_MemberJoinedBattle` 287, `_ParseConfig` 354, `GetDustCharacterURIFromCredential` 409, `OnInvokeSvcMethodFromClient` 487.
`dust/app.py`: `CalculateRoleMask` 273. `dust/startmini.py`: `GetBattleServices` 50, `InitApp` 251. `dust/userClient.py`: `OfflineConnect` 238, `_InitBattleServices` 293.
`dust/userBattle.py`: `NUM_OFFLINE_PLAYERS` 13, `OfflineConnect` 32. `dust/login.py`: `-autologinserver` 12, `OfflineLogin` 99.
`offline/offlineResourceMisc.py`: `OfflineBattles` 180. INIs: `PS3-DustEngine.ini` (`[URL] Port=7777`, `TcpNetDriver`), `PS3-DustGame.ini`
(`DefaultServerGame`, `DustGameSession`, `DustCheatManager`), `DustEngine-DedicatedServerCook.ini`.

## 14. Offene Fragen (Priorität)

1. **Skalierung:** 2 → 4 → 8 → 16 → 32 Clients messen (FPS, Tick, RAM, CPU je Thread). Bots gibt es nicht, also echte Clients oder
   mehrere Instanzen nötig.
2. Nach dem Messen entscheiden, ob RPCS3 reicht oder ein Recomp-Ansatz (ps3recomp) die Tick-Rate verbessern könnte.
3. Matchende, Belohnungen und Rückkehr in die Merc Quarters (`POST battle.completed`, `member.completed`) im CREST-Server.
4. Acquisition-Startposition, Ambush OMS testen, Absturz beim Moduswechsel.
5. Docker-Dauerbetrieb und Watchdog; ob RPCS3 die Interpreter-Varianten auf der Platte cached.
6. Warroom: `WB_WARROOM_CA` laden und prüfen, ob er als Vorphase vor der Gefechtskarte nutzbar ist.
