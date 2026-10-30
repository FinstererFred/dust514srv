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

## Hypothesen

- Der Tick am Host hängt nicht am Game-Thread: `main_thread` braucht nur 30 % eines Kerns und wartet den Rest der Zeit,
  vermutlich auf `RenderingThread`/RSX oder SPU-Jobs. Wenn das stimmt, kosten zusätzliche Spieler zunächst wenig, und der Hebel
  liegt beim Rendern auf dem Host (Null-Renderer, Effekte abschalten). Prüfen: dieselbe Messung im Null-Renderer-Host.
- Die SPU-Kernel-Last von 80–90 % ist möglicherweise größtenteils Warten (SPURS-Polling), keine echte Arbeit.
- Der Speicher pro Verbindung (Channels, Replikationsstate) könnte im emulierten 256-MB-Hauptspeicher knapp werden, auch wenn ein Client
  32 Pawns problemlos hält. Die 4,6 GB Host-RAM sagen darüber nichts.
- Untätige Test-Clients unterschätzen die Last am Host deutlich. Für aussagekräftige Messungen braucht es Bewegung und Schüsse.

## Ausprobiert

## Offene Fragen

- Gibt es Grenzen im NetDriver (MaxClients, Verbindungs-Arrays) oder in `sys_net`/RPCS3 (Sockets)? (Test mit 3–4 Clients)
- Wartet `main_thread` auf den RenderingThread, auf RSX oder auf SPU-Jobs? Wie sehen die Werte mit Null-Renderer aus?
- Wie lassen sich headless Clients mit Eingabe-Wiedergabe betreiben (Pad-Eingaben in RPCS3 skripten)?
