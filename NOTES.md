# Notizen

## Funde

- **Spielerobergrenze (2026-10-30, Host-Abbild `NPUB30643_guest_memory_20261027_142629_live`, Skirmish, 2 Spieler):**
  - `DustSkirmishGame_0`: `MaxPlayers=16`, `MaxPlayersAllowed=100`, `MaxSpectators=2`, `NumPlayers=2`. Die 16 kommt aus der Config
    (alle `Default__Dust*Game` haben 16; `Default__GameInfo` hat `MaxPlayersAllowed=32`, Dust hebt das auf 100).
  - `DustGRISkirmish_0`: `mMaxPlayersPerTeam=16`, `mMinPlayersPerTeam=0`. Pro Team passen also 16, zusammen 32. Die Gametypes
    heißen ohnehin `*_32p`.
  - **Die Grenze am Host ist `GameInfo.MaxPlayers=16` für beide Teams zusammen.** Ohne Änderung wird der 17. Spieler vermutlich
    abgewiesen (UE3 `AtCapacity` in `PreLogin`).
  - `InitGame` liest die URL-Option: Im Bytecode steht `MaxPlayers = Clamp(GetIntOption(Options, "MaxPlayers", MaxPlayers), 0,
    MaxPlayersAllowed)` (StringConst `MaxPlayers` bei 0x44a6d27e, Referenz auf `GameInfo.MaxPlayers` @0x42caea70). Mit
    `?MaxPlayers=32` in der Startzeile des Hosts (`dust_server/set_host_mode.py`, `start_command`) sollte die Grenze bei 32 liegen.
  - DustGame referenziert `AtCapacity` und `PreLogin`, überschreibt sie also möglicherweise. Ob dort eine eigene Grenze steckt,
    ist nicht geprüft.
  - Property-Offsets (PS3): `GameInfo.MaxSpectators` 0x214, `MaxPlayers` 0x220, `MaxPlayersAllowed` 0x224, `NumPlayers` 0x228;
    `DustGRI.mMinPlayersPerTeam` 0x380, `mMaxPlayersPerTeam` 0x384; `DustTeamInfo.mMaxSquadNum` 0x694, `mMaxPlayerNumOnSquads`
    0x69c (in den TeamInfos beider Abbilder 0). Werkzeug: `research/tools_local/uprops.py`.
  - Der CREST-Server meldet bereits `maxPlayers: 32` (`crest_app.py`). Laut `eveMimeTypes.py` ist `maxPlayersPerTeam` ein
    Feld der Battle-Daten aus dem Backend.

## Hypothesen

- Die Spielerzahl könnte zusätzlich zu `GameInfo.MaxPlayers` (siehe Funde) hart begrenzt sein: MaxClients im NetDriver, feste
  Verbindungs-Arrays, Socket-Limits in `sys_net`/RPCS3, eigene Prüfung in `DustTeamGame.PreLogin`/`AtCapacity`.
- Der Speicher pro Verbindung (Channels, Replikationsstate) könnte im emulierten 256-MB-Hauptspeicher knapp werden, auch wenn ein Client
  32 Pawns problemlos hält. Die 4,6 GB Host-RAM sagen darüber nichts.
- Untätige Test-Clients unterschätzen die Last am Host deutlich. Für aussagekräftige Messungen braucht es Bewegung und Schüsse.
- Die 26 FPS bei 2 Spielern sind vermutlich größtenteils Fixkosten (Welt, Physik, SPU-Jobs). Aussagekräftig sind die Kosten pro
  zusätzlichem Spieler.

## Ausprobiert

## Offene Fragen

- Hebt `?MaxPlayers=32` in der Host-Startzeile `GameInfo.MaxPlayers` wirklich auf 32? (Host starten, Abbild ziehen, mit
  `uprops.py` auf `DustSkirmishGame_0` +0x220 prüfen.)
- Prüft `DustTeamGame.PreLogin`/`AtCapacity` eine eigene Grenze, etwa `mMaxPlayersPerTeam` oder Squad-Größen?
- Gibt es weitere Grenzen im NetDriver (MaxClients, Verbindungs-Arrays) oder in `sys_net`/RPCS3 (Sockets)?
- Wie lässt sich der Server-Tick am Host zuverlässig messen, getrennt von der FPS?
- Wie lassen sich headless Clients mit Eingabe-Wiedergabe betreiben (Pad-Eingaben in RPCS3 skripten)?
