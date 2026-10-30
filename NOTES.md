# Notizen

## Nächste Session (Stand 2026-10-30)

Ziel: Skalierung über 5 Spieler messbar machen (CLAUDE.md Schritte 1–3). Der Host ist kein Engpass mehr (84 Ticks/s bei 5
Spielern), begrenzend sind jetzt die Test-Clients: Vulkan-Clients kosten so viel CPU, dass auf einem PC bei ~5 Schluss ist.

1. **Billige Test-Clients.** Null-Client läuft (`D:\rpcs3_e`, siehe Funde), braucht aber ≥ 2 Kerne, weil die Threads aktiv
   warten. `Max SPURS Threads: 1` erledigt (2 Kerne: 47 Hz). Nächste Hebel an der Render-Kette (RenderingThread +
   rsx::thread ~170 %), je eine Änderung: `Frame limit: 30` bzw. `-novsync` weg und VSync 30, RSX-Einstellungen (z. B.
   `Multithreaded RSX`), Spielargumente gegen Rendering. Ziel: ein Client auf 1 Kern bei ≥ 20 Hz und Spielzeit 1,0. Dann
   b–d umstellen.
2. **Eingabe-Wiedergabe.** Tastatur geht nur ans Fenster mit Fokus. Kandidat: virtuelle Gamepads (ViGEmBus-Treiber, Installation
   vorher mit dem Nutzer klären) pro Instanz plus RPCS3-Hintergrundeingabe, gesteuert per Skript (laufen, drehen, schießen).
3. **Speicher in der emulierten PS3.** Freien Hauptspeicher (256 MB) bei 5 Spielern auslesen (z. B. `sys_memory_get_user_memory_size`
   bzw. RPCS3-Speicherstatistik) und auf 32 hochrechnen. Harte Grenze, die keine Tick-Messung zeigt.
4. Danach: Clients auf einem zweiten PC, Messreihe 8 → 16 → 32 mit `tools/host_tick.py`.

Zustand am Ende der Session: Host `D:\rpcs3` mit Null-Renderer-Config (Vulkan-Original in
`config_NPUB30643.yml.before_nulltick`), Weltrendering-Patch aktiv, Start mit `-novsync`. Test-Clients `D:\rpcs3_b`…`_e`
(Vulkan, Bind 127.0.0.2–.5, CREST-Ports 8081–8084, RPCN DustTester2–5). Mess-Hilfen im Scratchpad gehen verloren; das Muster
war: Client starten, auf `NumPlayers` warten, `host_tick.py` 30 s laufend und 8 s mit suspendierten Clients (psutil).
Docker: `export_host_data.ps1` erneut ausführen, damit der Weltrendering-Patch in den Datenordner kommt; `docker/.env` hat
`-novsync` schon.

## Funde

- **Null-Renderer-Test-Client funktioniert, ist aber nicht billig (2026-10-30, `D:\rpcs3_e`):** Config wie Host (Null, `PS3 Native`,
  Depth-Buffer aus, Backup `*.before_nullclient`), Patch „disable world rendering“ an (LOD-Patch aus), Start mit oder ohne
  `-novsync`. Beitritt nach ~1,5 min, Spawn mit V (X nur nach einem Disconnect), Bewegung (W) kommt beim Host an. Treffer
  ungetestet. Ohne Bild prüft `tools/pawn_list.py` Spawn und Position (WorldInfo.PawnList; auf einem Client hat nur der
  eigene Pawn einen Controller). Gemessen mit `host_tick.py --exe <client>` (30 s, gespawnt, untätig, ohne Pinning):

  | Client | Hz | Prozess-CPU | RSS |
  |---|---|---|---|
  | Vulkan (d) | 21,6 | 671 % | 4,5 GB (private 5,7 GB) |
  | Null, `-novsync` (e) | 85,8 | 506 % | 2,4 GB |
  | Null, VSync (e) | 59,4 | 493 % | 2,4 GB |

  Die Frame-Grenze spart keine CPU: RenderingThread (88 %), rsx::thread (79 %) und die SPURS-Kernel (~42 %) warten aktiv.
  Mit Affinität (VSync): 1 Kern (2 logische) 6 Hz, Spielzeit 0,93, unbrauchbar; 2 Kerne 27 Hz, Spielzeit 1,0; 4 Kerne 60 Hz.
  Ein Client braucht also mindestens 2 Kerne, auf dem 5900X neben dem Host (CCD0) nur ~3 Clients auf CCD1. Host blieb bei
  83–88 Ticks/s mit einem Null-Client; mit zusätzlichem ungepinntem Vulkan-Client fiel er auf 69,5 (CPU-Konkurrenz).
- **`Max SPURS Threads` am Null-Client senken hilft (2026-10-30, `D:\rpcs3_e`, Backup `*.before_spurs`, jetzt 1):** Es bleiben
  6 Kernel-Threads, RPCS3 lässt aber nur N gleichzeitig laufen. VSync, gespawnt, untätig, 30 s:

  | Max SPURS | ungepinnt | 4 Kerne | 2 Kerne | 1 Kern |
  |---|---|---|---|---|
  | 6 | 59 Hz, 493 % | 60 Hz, 498 % | 27 Hz | 6 Hz, Spielzeit 0,93 |
  | 2 | 59 Hz, 458 % | – | 39 Hz | – |
  | 1 | 58 Hz, 398 % | – | 47 Hz | 9 Hz, Spielzeit 0,95 |

  Beitritt, Spawn (V) und Bewegung funktionieren mit 1. Ein Kern bleibt unbrauchbar. Jetzt dominieren RenderingThread (~90 %) und
  rsx::thread (~80 %), also die Render-Kette trotz Null-Renderer und Weltrendering-Patch. Achtung beim Warten auf den Beitritt:
  „Client sieht Pawns“ taugt nicht als Kriterium, wenn am Host niemand gespawnt ist.
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
  | 4 gespawnt, c läuft und schießt | 83,9 (p95 18,5 ms) | 11,9 | 89,0 | 86 % / 67 % |

  Gespawnte untätige Pawns kosten ohne Weltrendering nur noch ~0,1 ms pro Tick (vorher ~1,5 ms); die frühere Pawn-Last war also
  fast ganz Rendering. Jetzt begrenzt der Game-Thread (fast ein voller Kern). Bei 30 Ticks/s Ziel bleiben rund 21 ms Reserve
  pro Tick.
- **`-novsync` fest im Host-Start (2026-10-30):** `tools/restart_host.ps1`, `docker/host/watchdog.py`, `docker/compose.yaml`,
  `docker/.env.example`. Eine lokale `docker/.env` mit eigenem `HOST_GAME_ARGS` überschreibt das und muss von Hand nachgezogen
  werden. Host-Config (Windows) zurück auf `Frame limit: PS3 Native`; mit `-novsync` begrenzt das nicht mehr: 86,3 Ticks/s bei
  5 verbundenen Spielern, Spielzeit 1:1. Freies Laufen kostet kaum CPU (Prozess 486 % gegen 480 % bei 60 Hz mit VSync), daher
  vorerst ohne festes Limit. Vorteil gegenüber VSync: ein Tick über 16,7 ms wird nicht auf 30 oder 20 Hz abgerundet.
- **Teams automatisch:** `listen_team: "auto"` in `fake_battle.json` verteilt Beitretende abwechselnd (erster → Verteidiger,
  `Team=1`; zweiter → Angreifer, `Team=0`). Nachbeitritte zählen als neue Mitglieder, das ist also nur grob ausgeglichen.
  `dust_server/dev_once.py` schickt einzelne Konsolenbefehle an den laufenden Host, ohne die Karte neu zu starten.
- **Charakter-Server 1a (2026-10-30), hinter `DUST_CHAR_STORE=1`, standardmäßig aus:** Ohne Schalter liefert der Server
  nachweislich dieselben Antworten und Log-Quellen wie vorher (Vergleich alter/neuer `crest_app` im Prozess). Mit Schalter:
  eigener Token pro RPCN-Konto (Online-ID aus dem `psn_ticket`), SQLite `dust_server/state/dust.sqlite`, automatischer
  Startcharakter (Amarr-Enforcer, Name = Online-ID, 500 000 SP, 8 Start-Skills, 25 000 ISK aus CATMA `/specialties`).
  Konten in `DUST_HOST_ACCOUNTS` (Standard `DustHost`) und alle Anfragen mit dem alten Token bleiben auf CCPs Offline-Daten.
  Nur im Prozess getestet, **noch nicht in RPCS3**. Funde dabei:
  - Der Client holt `/roots/dust/` **ohne** Token. Die Root-Links `user`/`character` können also nicht pro Benutzer sein und
    zeigen weiter auf 1000000720/2100001611. Der Benutzer kommt über `/decode/`. Ob der Client den Root-`character`-Link
    irgendwo nutzt, beim RPCS3-Test prüfen.
  - Der Login schickt `Authorization: Basic …` (Client-Kennung), alle späteren Anfragen `Bearer <token>`.
  - RPCN-Ticket: 254 Byte, Online-ID im 6. Element des Body-Abschnitts. `np_ticket.build()` erzeugt dasselbe Layout für Tests.
  - Für den RPCS3-Test: Lokal ist FinstererFred der Host → `DUST_HOST_ACCOUNTS=FinstererFred`. Test-Clients starten mit
    `-autologincharindex=1`, haben mit Schalter aber nur einen Charakter → Index 0 verwenden.
  - ISK in der Charakterliste kommt schon aus der Datenbank (25 000), die Wallet-Seiten noch aus `wallet.json` (Stufe 1b).
- **Stufe 1b (2026-10-30), ebenfalls hinter dem Schalter:** Alle übrigen Pfade mit einer eigenen Charakter-ID (Mail, Chat,
  Quests, Fittings, Skills, Inventar, Corp-Mitglied …) fragen CCPs Handler mit 2100001611 und tauschen die IDs aus
  (Log-Quelle `ccp_offline:rebind`). Nur der Besitzer bekommt sie, sonst 404. ISK unter `/accounts/{id}/` kommt aus
  `characters.isk`, AUR und LP bleiben global. Wieder im Prozess geprüft: ohne Schalter identisch zum Stand vor 1a (24
  Anfragen), mit Schalter keine Offline-IDs mehr in den Antworten eigener Charaktere.
- **Stufe 2 (2026-10-30), hinter dem Schalter:** Echte Skills pro Charakter. Funde aus dem Client-Code:
  - Einen Skill freischalten heißt **Skillbuch lesen**: `POST …/skills/ {skillTypeID}` macht ihn mit **Stufe 0** bekannt
    (kostet keine SP, `IsSkillNeedReadBook` = Stufe `None`). Erst `PUT …/skills/{id}/ {currentLevel, aimLevel}` kostet SP. Der
    Plan nahm Stufe 1 beim Kauf an, das war falsch. Das Buch selbst ist ein Inventar-Item (gleiche typeID) und kostet ISK im
    Markt (`basePrice`, z. B. 149 000). Abgezogen wird es noch nicht, weil CCPs Inventar 999 von allem hat (Stufe 5).
  - Kostentabelle in `.pyo`: `[6220, 18650, 43530, 87060, 155460]` × `costMultiplier`. Der Decompiler zeigt fälschlich
    `[19, 20, 21, 22, 23]`, also immer den echten Wert über py27 nachprüfen.
  - Der Client fängt bei Skill-Aufrufen keine HTTP-Fehler ab (ein Fehler wäre eine ungefangene Ausnahme, also eine Trennung).
    Abgelehnte Käufe beantworten wir daher mit 200 und einem Log-Eintrag `skills: … rejected: …`. Der Client lädt die Skills
    danach ohnehin neu.
  - Startcharakter: 136 830 SP stecken in den 8 Start-Skills, 363 170 sind frei.
  - Admin-Seite „Characters“: Konten und Charaktere anzeigen, Gesamt-SP und ISK setzen, Skills auf den Startstand
    zurücksetzen. Ohne Schalter wird die Datenbank nicht geöffnet.
  - **Live-Updates (2026-10-30):** Admin-Änderungen (Gesamt-SP, einzelne Skills, Reset) und das Umschalten des passiven
    Zuwachses gehen sofort an einen eingeloggten Client, über `OnCharacterSkillPointChange-v1` bzw. `OnCharacterSkillChange-v1`
    im Stream des Charakters. Der Client hängt selbst `FromBackend` an den Namen an. `cycleCap`/`skillPointsThisCycle` senden
    wir als 0, der Client speichert sie nur. Im Prozess geprüft, in RPCS3 noch offen: Aktualisiert der Skill-Bildschirm sich
    sichtbar?
  - Admin-Seite „Characters“: Pro Charakter lässt sich die Skill-Liste aufklappen, mit Stufe 0–5 je Skill, Entfernen und
    Hinzufügen per Name. Es gibt keine Prüfung von Voraussetzungen und SP. „Save“ schickt nur geänderte Felder (sonst würden
    die angezeigten, schon veralteten Gesamt-SP den passiven Zuwachs überschreiben). Im Browser auf einer Testinstanz geprüft.
  - **Vor einem Server-Neustart für Messungen:** `python tools/legacy_parity.py` (2 s, braucht den CATMA-Dienst) zeigt, ob
    der Server ohne Schalter noch genau wie vor 1a antwortet. Er ist auch Teil der Unit-Tests.
  - Geprüft im Prozess: ohne Schalter 26 Anfragen identisch (auch Skill-POST/PUT), mit Schalter Buch, Upgrade und die vier
    Ablehnungsfälle. In RPCS3 noch offen: Zeigt der Skill-Bildschirm die freien SP richtig, und klappt Upgraden ohne Trennung?

## Hypothesen

- **Host rendert trotz Weltrendering-Patch weiter (2026-10-30):** Host, 2 Spieler, 84 Ticks/s: RenderingThread 81 %, main_thread
  78 %, rsx::thread 59 %, `_gcm_intr_thread` 27 %, SPURS-Kernel je 37–46 %. `bDisableWorldRendering` spart nur die 3D-Szene;
  HUD/Canvas, Scaleform, Post-Processing, Clear und Flip laufen weiter. Kostet ~1,7 Kerne pro Host-Instanz (wichtig für mehrere
  Hosts pro Maschine) und bremst den Tick möglicherweise noch über die Frame-Synchronisation Game-/Render-Thread. Hebel erst am
  Null-Client testen (gefahrlos), dann am Host mit Tick- und Kollisionsmessung. `Max SPURS Threads` am Host nur mit Messung
  senken: dort laufen eventuell Physik-/Animations-Jobs, die der Server braucht.
- Der Tick am Host hängt an der Render-Kette (Game-Thread wartet auf `RenderingThread` → RSX-FIFO in RPCS3), auch mit
  Null-Renderer. Mehr Pawns bedeuten mehr Zeichenbefehle. Hebel wäre, das Rendern am Host weitgehend abzuschalten (UE3
  `show`-Flags, Viewport nicht zeichnen, Patch im RenderingThread). Ein Recompiler für den PPU-Code würde daran wenig ändern.
- Die SPU-Kernel-Last von 80–90 % ist möglicherweise größtenteils Warten (SPURS-Polling), keine echte Arbeit.
- Der Speicher pro Verbindung (Channels, Replikationsstate) könnte im emulierten 256-MB-Hauptspeicher knapp werden, auch wenn ein Client
  32 Pawns problemlos hält. Die 4,6 GB Host-RAM sagen darüber nichts.
- Untätige Test-Clients unterschätzen die Last am Host deutlich. Für aussagekräftige Messungen braucht es Bewegung und Schüsse.

## Ausprobiert

- **`Frame limit: Auto` am Windows-Host (2026-10-30):** Host kam nur extrem langsam hoch (12–60 s zwischen den Login-Anfragen).
  Bekannt: ohne den eigenen RPCS3-Build schläft der Null-Renderer bei Auto an jedem Flip (`handle_emu_flip`). Zurück auf
  `PS3 Native`. `Vblank Rate: 120` hob die 60er-Grenze ebenfalls nicht (VSync wartet im Spiel), zurückgenommen.

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
- **Fahrzeuge (Panzer, Dropships), zurückgestellt bis nach den Performance-Tests (Entscheidung 2026-10-30):** Technisch
  sollte es gehen. Der Client schickt sein Fitting beim Spawn bzw. Anfordern an den Host (`DeployVehicleWithFitting`), der
  Host hat alle Items 999× und alle Skills auf Stufe 5. CCPs Fitting-Liste im CATMA-Dienst kann neue Fittings anlegen (POST),
  ist aber gemeinsam für alle, nach einem Neustart weg und vergibt beim ersten POST ID 101 doppelt. **Der POST scheitert in
  unserem CATMA-Dienst ohnehin** (`GetDisplayNameByID` braucht den Lokalisierungsdienst: „sake application instance has not
  been initialized yet“, geprüft 2026-10-30, auch mit 2100001611). Neue Fittings im Spiel anzulegen geht also heute nicht. Der
  Weg führt über eigene Fittings vom Server. Offen sind drei Punkte:
  Bietet der Fitting-Bildschirm Fahrzeuge an? Liefert der Listen-Server das RDV aus? In welchen Modi gibt es Fahrzeuge
  (vermutlich Skirmish/Domination, nicht Ambush)? Erster Versuch im Spiel, sonst fertige Fittings vom Server
  (`content/fittings.json`, Vorgriff auf Stufe 5).
