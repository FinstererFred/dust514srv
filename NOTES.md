# Notizen

## Funde

- **Keine Spielerobergrenze im UnrealScript (2026-10-30):**
  - `DustTeamGame.AtCapacity` ist überschrieben und gibt immer `false` zurück. Die UE3-Prüfung `NumPlayers >= MaxPlayers` in
    `GameInfo.AtCapacity` greift damit nie. `DustTeamGame.Login` weist nur ab, wenn Charakter-ID oder Character-URI fehlen,
    `PickTeam` übernimmt das angefragte Team (255 → 0), `ChangeTeam` prüft nur Zuschauer.
  - `GameInfo.MaxPlayers` ist per Config 16 (alle `Default__Dust*Game`), `MaxPlayersAllowed` 100. Der Host startet seit
    `450eaa0` mit `?MaxPlayers=32` (`InitGame`: `Clamp(GetIntOption(Options, "MaxPlayers", …), 0, MaxPlayersAllowed)`),
    im Live-Abbild bestätigt. Wegen `AtCapacity` ist das nicht nötig, schadet aber nicht und hält Anzeigen konsistent.
  - `DustGRI.mMaxPlayersPerTeam` (live 16) wird nur in `DustTeamGame.PostBeginPlay` gesetzt, also nur zur Anzeige.
    `DustTeamInfo.mMaxSquadNum`/`mMaxPlayerNumOnSquads` liest nur `MatchOver.DetermineMatchResult`.
  - Ungeprüft bleiben native Grenzen: NetDriver (C++) und `sys_net`/RPCS3. Das zeigt erst ein Test mit mehr als 2 Clients.
  - Property-Offsets (PS3): `GameInfo.MaxSpectators` 0x214, `MaxPlayers` 0x220, `MaxPlayersAllowed` 0x224, `NumPlayers` 0x228;
    `DustGRI.mMinPlayersPerTeam` 0x380, `mMaxPlayersPerTeam` 0x384; `DustTeamInfo.mMaxSquadNum` 0x694,
    `mMaxPlayerNumOnSquads` 0x69c; `WorldInfo.TimeDilation` 0x454, `TimeSeconds` 0x45c, `RealTimeSeconds` 0x460,
    `DeltaSeconds` 0x468. UProperty-Offset steht bei +0x5c. Werkzeuge: `research/tools_local/uprops.py` (Offsets und
    Werte aus Abbildern), `uscript.py` direkt auf `COOKEDPS3/DUSTGAME.XXX` und `ENGINE.XXX` (beide unkomprimiert).
- **Tick-Messung:** `tools/host_tick.py` liest im laufenden RPCS3 `WorldInfo.RealTimeSeconds` in einer engen Schleife (jede
  Änderung = ein Engine-Tick), dazu CPU je Thread und RAM. Die WorldInfo findet es über die vtable `0x01998b10`; im Heap liegen
  viele veraltete Kopien, genommen wird die, deren Zeit läuft. Nur Windows (ReadProcessMemory), nicht im Docker-Host.
- **Ausgangswerte (2026-10-30, lokaler Host mit GPU, Ryzen 9 5900X, Ambush-Deploy-Karte, nur Host, 30 s):**
  24,9 Ticks/s, Intervall Mittel 40,2 ms, p95 54,9 ms, max 68,9 ms, Spielzeit läuft 1:1. RPCS3 gesamt 690 % CPU, RSS 4,5 GB.
  Threads: `rsx::thread` 93 %, sechs `MainCellSpursKernel` je 82–92 %, PPU `RenderingThread` 44 %, PPU `main_thread` 30 %,
  PhysX 1 %.

- **Null-Renderer-Host (2026-10-30, Frame limit PS3 Native):** 31,5–31,8 Ticks/s statt 24,9 mit Vulkan, RSS 2,4 statt 4,5 GB.
  Am Host bremst also das Rendern, nicht die Spiellogik.
- **Skalierung 1 → 5 Spieler (2026-10-30, alles auf einem PC):** Host mit Null-Renderer auf CCD0 (CPU 0–11), Clients
  `rpcs3_b`–`rpcs3_e` (Vulkan) auf CCD1 (12–23). „Angehalten“ = alle Client-Prozesse 8 s suspendiert, zeigt die reinen
  Kosten am Host ohne CPU-Konkurrenz. Rohdaten: `dust_server/logs/host_tick.jsonl` (lokal).

  | Spieler (Host + Clients) | Zustand | Ticks/s laufend | Ticks/s angehalten |
  |---|---|---|---|
  | 1 | – | 31,5 | – |
  | 2 / 3 | im Deploy-Bildschirm, nicht gespawnt | 29,1 / 26,6 | 32,4 / 32,4 |
  | 2 / 3 / 5 | gespawnt, untätig (Abwärtsreihe) | 27,6 / 24,4 / 22,6 | 29,7 / 27,7 / 26,5 |

  Ungespawnte Spieler kosten den Host praktisch nichts. Jeder gespawnte Pawn kostet grob 1,5 ms pro Tick
  (31,8 ms → 38 ms bei 4 Remote-Pawns). Linear hochgerechnet wären es bei 32 untätigen Spielern ~78 ms, also ~13 Ticks/s.
  Das ist nur ein grober Anhaltspunkt: wenige Punkte, untätige Pawns, Clients auf demselben PC, `NumPlayers` sinkt nach
  dem Beenden eines Clients erst nach dem Verbindungs-Timeout. Der `main_thread` bleibt dabei bei 30–37 % eines Kerns,
  `RenderingThread` bei ~30 %, `rsx::thread` bei 60–70 %. Auch mit Null-Renderer ist der Game-Thread also nicht der Engpass.
- **Idle-Kick:** `GameInfo.MaxIdleTime` ist 0 (setzbar über `DustServerConfig` `[battle] idleKickTime` in
  `DustTeamGame.LoadBattleConfig`). Es kickt `DustPlayerController` im Zustand `Dead` (Deploy-Bildschirm, kein Spawnpunkt):
  nach `mAllowedIdleTime` (30 s) `WarnPlayerToRespawn`, dann Chess-Timer `mChessRespawnTime` → `KickIdlePlayer`. Beobachtet
  wurden 7–8 min bis zum Kick. Mit `-autologinbattle` tritt der Client danach von selbst wieder bei. Gespawnte Spieler betrifft
  das nicht.
- **Mehrere Test-Clients auf einem PC:** Alle sprechen HTTP von 127.0.0.1 (die RPCS3-Bind-Adresse gilt nur für Spielsockets).
  Deshalb braucht jeder Client einen eigenen CREST-Port (8081–8084, `TEST_CLIENT_PORTS` in `crest_app.py`). Benachrichtigungen
  gehen an Adresse plus Port (`client_key`). Vorher bekamen alle Clients auf 8081 jede Beitrittsnachricht, und ein früherer Client
  hat sich mit der Credential des neuen verbunden. Instanzen: `D:\rpcs3_b` … `D:\rpcs3_e`, Bind 127.0.0.2–.5, RPCN-Konten
  DustTester2–5 auf dem lokalen RPCN (`research/rpcn/test_account*.txt`). Spawnen per `tools/press_key.ps1` (erst X für
  Dialoge, dann V = Dreieck/Smart Deploy).

- **Weltrendering am Host abschalten (2026-10-30):** `DustGameViewportClient_0` (+0xb4, Bit 0x10000000 =
  `bDisableWorldRendering`) per `tools/guest_poke.py` gesetzt. Null-Renderer-Host, 4 gespawnte untätige Clients:
  24,7 → **58,5 Ticks/s** (p95 50 → 21 ms), wieder an: 25,1. Nur Host: 35,7 → 59,4. Prozess-CPU 600 → 490 %. Danach
  bestimmt erst der Game-Thread (64 % eines Kerns ≈ 11 ms pro Tick bei 5 Spielern). Konsolenbefehl `set` wirkt im
  Retail-Build nicht, Show-Flags sind herauskompiliert, kein Skript setzt das Flag. Patch-Entwurf:
  `rpcs3_patches/host_disable_world_rendering.yml` (drei `rlwinm` → `li r3,1` in der Viewport-Funktion ab 0x31b808).
- **Patch „Listen host: disable world rendering“ getestet (2026-10-30):** Im Host installiert (`D:\rpcs3\patches`, Backup
  `*.before_worldrender`), RPCS3-Log meldet „Applied patch“. Nur Host: 59,2 Ticks/s (p95 19,8 ms, Prozess-CPU 478 %, RSS 2,36 GB).
  2/3 Spieler (Clients noch im Deploy-Bildschirm): 55,5/57,1 laufend, 59,0/59,2 angehalten. Funktionstest bestanden: Kollision
  fern vom Host in Ordnung (Nutzer lief herum), Treffer zwischen zwei Clients verschiedener Teams kommen an, Client c hat
  Client b getötet.
  Mit 5 Spielern, davon 4 gespawnt und untätig (vom Nutzer deployt, Teams 1/0/1/0): **57,4 Ticks/s** laufend (p95 22,8 ms,
  max 78,9 ms), 59,4 angehalten (p95 20,6 ms). Vorher ohne Patch: 22,6 bzw. 26,5. `main_thread` 60–76 %, `RenderingThread`
  75–85 %, `rsx::thread` 69–77 %, Prozess 483–505 %, RSS 2,37 GB. Der Host liegt damit am Frame-Limit (PS3 Native ≈ 60);
  wie viel Luft darüber bleibt, zeigt erst ein Lauf mit Frame limit Off.
  Ein Client aktiv (Nutzer läuft mit c herum und schießt auf b/d, 30 s): 57,5 Ticks/s laufend (p95 22,8 ms, max 54,9 ms),
  59,4 angehalten, `main_thread` 77 %. Kein messbarer Unterschied zu untätig, solange der Host am Frame-Limit hängt.
- **60er-Grenze ist VSync im Spiel, Kommandozeile `-novsync` hebt sie auf (2026-10-30):** Host mit Patch, Null-Renderer.
  RPCS3 `Frame limit: Off` allein: 59,0 Ticks/s; zusätzlich `Vblank Rate: 120`: 58,5 (zurückgenommen). Das EBOOT kennt
  `UseVsync`/`novsync`; mit Spielargument `-novsync` (nach `--` an RPCS3, steht im TTY.log als CommandLine) läuft der Host frei,
  Spielzeit weiter 1:1 (`game_speed 1.0`). Host-Config jetzt `Frame limit: Off` (Backup `*.before_nolimit`).

  | 5 Spieler, `-novsync` | Ticks/s laufend | ms/Tick | Ticks/s angehalten | `main_thread` |
  |---|---|---|---|---|
  | verbunden, nicht gespawnt | 87,3 | 11,5 | – | 77 % |
  | 4 gespawnt, untätig | 84,0 (p95 18,0 ms) | 11,9 | 89,5 (11,2 ms) | 88 % / 70 % |

  Gespawnte untätige Pawns kosten ohne Weltrendering nur noch ~0,1 ms pro Tick (vorher ~1,5 ms); die frühere Pawn-Last war also
  fast ganz Rendering. Jetzt begrenzt der Game-Thread (fast ein voller Kern). Bei 30 Ticks/s Ziel bleiben rund 21 ms Reserve
  pro Tick. Der Host-Start mit `-novsync` ist noch nicht dauerhaft eingetragen (`restart_host.ps1`, `set_host_mode.py`, Docker);
  für den Betrieb wäre ein festes Limit sinnvoller als freies Laufen (CPU).
- **Teams automatisch:** `listen_team: "auto"` in `fake_battle.json` verteilt Beitretende abwechselnd (erster → Verteidiger,
  `Team=1`; zweiter → Angreifer, `Team=0`). Nachbeitritte zählen als neue Mitglieder, das ist also nur grob ausgeglichen.
  `dust_server/dev_once.py` schickt einzelne Konsolenbefehle an den laufenden Host, ohne die Karte neu zu starten.

## Hypothesen

- Der Tick am Host hängt an der Render-Kette (Game-Thread wartet auf `RenderingThread` → RSX-FIFO in RPCS3), auch mit
  Null-Renderer. Mehr Pawns bedeuten mehr Zeichenbefehle. Hebel wäre, das Rendern am Host weitgehend abzuschalten (UE3
  `show`-Flags, Viewport nicht zeichnen, Patch im RenderingThread). Ein Recompiler für den PPU-Code würde daran wenig ändern.
- Die SPU-Kernel-Last von 80–90 % ist möglicherweise größtenteils Warten (SPURS-Polling), keine echte Arbeit.
- Der Speicher pro Verbindung (Channels, Replikationsstate) könnte im emulierten 256-MB-Hauptspeicher knapp werden, auch wenn ein Client
  32 Pawns problemlos hält. Die 4,6 GB Host-RAM sagen darüber nichts.
- Untätige Test-Clients unterschätzen die Last am Host deutlich. Für aussagekräftige Messungen braucht es Bewegung und Schüsse.

## Ausprobiert

- **`restart_all` mit Null-Renderer-Host (2026-10-30):** Der Host blieb zweimal vor der Charakterauswahl hängen (nach
  `/dust/asset/bundle/offline` nur noch Keepalives). Nur den Host neu zu starten (`restart_host.ps1`) half jedes Mal. Für den
  Watchdog wichtig: Ursache offen.

## Offene Fragen

- Gibt es Grenzen im NetDriver oder in `sys_net`/RPCS3? Bis 5 Spieler keine.
- Wie skaliert der Game-Thread (~11 ms/Tick bei 5 Spielern) mit aktiven Spielern und mit mehr als 5? Wie hält man den Host
  ohne VSync auf einem festen Takt (z. B. 30 oder 60), damit er nicht unnötig CPU verbrennt?
- Wie teuer sind aktive Spieler (Laufen, Schießen) im Vergleich zu untätigen Pawns?
- Ab wie vielen Clients lohnt ein zweiter PC, damit die CPU-Konkurrenz die Messung nicht verfälscht?
- Wie lassen sich headless Clients mit Eingabe-Wiedergabe betreiben (Pad-Eingaben in RPCS3 skripten)?
