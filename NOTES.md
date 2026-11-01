# Notizen

## Nächste Session (Stand 2026-10-30)

Ziel: Skalierung über 5 Spieler messbar machen (CLAUDE.md Schritte 1–3). Der Host ist kein Engpass mehr (84 Ticks/s bei 5
Spielern), begrenzend sind jetzt die Test-Clients: Vulkan-Clients kosten so viel CPU, dass auf einem PC bei ~5 Schluss ist.

0. **Messreihe mit Fake-Clients fortsetzen.** Spawn und Laufen gehen (siehe Funde). Nächstes: 16 → 32 Fake-Clients
   (`--play`, je eigene Bind-Adresse 127.0.x.y), dabei Fake-Client-CPU pro Prozess messen (ab ~16 evtl. auf zweiten PC).
   Schießen geht mit `--fitting assault --fire-interval 5 --fire-burst 2` (siehe Funde). Ungetestet: Treffer auf andere
   Spieler, Tod und Respawn eines Fake-Clients (Spawn-Logik läuft dann erneut, `armed` wird bei neuem Pawn zurückgesetzt).
1. **Billige Test-Clients (RPCS3, zurückgestellt).** Null-Client läuft (`D:\rpcs3_e`, siehe Funde), braucht aber ≥ 2 Kerne, weil die Threads aktiv
   warten. `Max SPURS Threads: 1` erledigt (2 Kerne: 47 Hz). Nächste Hebel an der Render-Kette (RenderingThread +
   rsx::thread ~170 %). `Frame limit: 30` scheidet aus (siehe Ausprobiert). Bleibt: das Rendern selbst weiter abschalten
   (Ghidra: Viewport-Draw bzw. HUD/Scaleform/Post-Processing überspringen, Game-Thread muss weiter ticken), gilt dann auch
   für den Host. Ziel: ein Client auf 1 Kern bei ≥ 20 Hz und Spielzeit 1,0. Dann b–d umstellen.
2. **Eingabe-Wiedergabe.** Tastatur geht nur ans Fenster mit Fokus. Kandidat: virtuelle Gamepads (ViGEmBus-Treiber, Installation
   vorher mit dem Nutzer klären) pro Instanz plus RPCS3-Hintergrundeingabe, gesteuert per Skript (laufen, drehen, schießen).
3. ~~**Speicher in der emulierten PS3.**~~ Erledigt: 213 MB von 256 MB Heap bei 32 Spielern (siehe Funde).
4. Danach: Clients auf einem zweiten PC, Messreihe 8 → 16 → 32 mit `tools/host_tick.py`.

Zustand am Ende der Session: Host `D:\rpcs3` mit Null-Renderer-Config (Vulkan-Original in
`config_NPUB30643.yml.before_nulltick`), Weltrendering-Patch aktiv, Start mit `-novsync`. Test-Clients `D:\rpcs3_b`…`_e`
(Vulkan, Bind 127.0.0.2–.5, CREST-Ports 8081–8084, RPCN DustTester2–5). Mess-Hilfen im Scratchpad gehen verloren; das Muster
war: Client starten, auf `NumPlayers` warten, `host_tick.py` 30 s laufend und 8 s mit suspendierten Clients (psutil).
Docker: `export_host_data.ps1` erneut ausführen, damit der Weltrendering-Patch in den Datenordner kommt; `docker/.env` hat
`-novsync` schon.

## Funde

- **Docker-Datenordner aktualisiert, RPCS3-Stand im Image (2026-11-01):** `export_host_data.ps1` neu ausgeführt
  (Sicherungen `*.before_export1101`, alte `COMMON.SDAT` als `D:\dust514-data\COMMON.SDAT.before_export1101`). Vorher
  fehlten im Datenordner die COMMON.SDAT vom 31.10. (Matchende-Hook, RDV-pending-Fitting) sowie Patch 0.6/0.7 und
  RDV 0.3 samt Eintrag in `patch_config.yml`; jetzt bitgleich zu `D:\rpcs3`. Das Export-Skript las die Config als ANSI
  (Midi-Zeile verstümmelt), jetzt `-Encoding UTF8`. Images neu gebaut, Stack **noch nicht gestartet** (lokaler Stack
  belegte die Ports). RPCS3 im Image ist fest auf `e53ac18f` (v0.0.43) gepinnt, ein automatisches Update gibt es nicht.
  Upstream-Master (`fab15ea`, 31.10.) hat das RSX umgebaut (`Core/RSXDisplayEngine.cpp`, `GSRender.cpp` gibt es nicht
  mehr), `null-renderer-flip.patch` greift nicht mehr. Dafür löscht `display_engine::flip` die Emu-Flip-Anforderung
  jetzt zentral für alle Renderer, der Patch ist dort also vermutlich überflüssig. Ungetestet: Build ohne Patch,
  Null-Renderer mit `Frame limit: Auto`, Tick-Messung gegen den gepinnten Stand.

- **`Thread Scheduler Mode: RPCS3 Scheduler` am Host: +25 % Tick bei 32 Spielern (2026-10-30, übernommen):** 32 feuernde
  Fake-Clients, je Lauf Host-Neustart und zwei 30-s-Fenster `host_tick.py`, Varianten abwechselnd. RPCS3-Scheduler
  22,8 / 23,0 / 24,5 / 22,8 / 27,6 / 24,4 (Mittel 24,2 Ticks/s, p95 49–72 ms), Betriebssystem-Scheduler 20,4 / 21,3 / 18,7 /
  18,5 / 19,6 / 16,8 / 19,5 / 20,6 (Mittel 19,4, p95 63–84 ms). Jeder RPCS3-Scheduler-Lauf lag über jedem Basislauf. Alle
  Läufe 32/32 gespawnt, Host stabil. Gesetzt in `D:\rpcs3\config\custom_configs\config_NPUB30643.yml` (Backup
  `*.before_sched`). Docker: dieselbe Zeile in die Host-Config im Datenordner (README ergänzt); unter Linux nicht gemessen.
  Abstand zu 30 Hz bei 32 Spielern jetzt ~1,25x statt 1,6x.

- **Fake-Clients meldeten falsche Level-Namen, korrigiert (2026-10-30):** Mess-Patch mit Zählern in
  `ClientHasInitializedLevelFor` (FUN_005ea628): mit 16 Fake-Clients ~100 000 Suchen/s in `ClientVisibleLevelNames`,
  0,0 % Treffer. Vergleich im Host-Speicher (PlayerController+0x2f0 → UNetConnection, Liste +0x5060, Weltname +0x5058,
  bei allen korrekt): echter Client 62 von 64 Namen bekannt, Fake-Client 20 von 158. Outpost-Level sind instanziert
  (`CS_GA_SecScan01S_LOD0_3`, `_4`, …); die Nummer ist die Instanz des Hosts, nicht der Kanal. Folge: Der Host hielt bei
  Fake-Clients fast alle Outpost-Level für nicht geladen (keine Replikation ihrer Actors, jede Prüfung scannt die ganze
  Liste). Echte Clients melden die vollen Level (`X`, `X+AU`) nur für das Outpost in ihrer Nähe.
  Fix: `tools/host_levels.py` liest die Streaming-Level des Hosts (179 auf MN_Craters01) nach
  `research/levels/<Welt>.json`, `fake_client.py` meldet diese (`--levels`, automatisch bei genau einer Datei;
  `--full-levels all|none`). Danach 100 % Treffer und nur noch Dutzende Suchen/s. Neue Messung (frischer Host, volle
  Level für alle Outposts gemeldet, also eher mehr Last als echte Clients):

  | Clients | vorher (falsche Namen) | korrigiert | korrigiert + Move-to-Front |
  |---|---|---|---|
  | 16 | 39,3 | 45,4 | 46,9 |
  | 32 | 16,6 | 18,3 | 15,95 |

  Der 18-%-Hotspot im PPU-Profil war ein Artefakt der falschen Namen. Move-to-Front
  (`rpcs3_patches/host_level_visibility_mtf.yml`) bringt nichts Messbares und ist nicht installiert; nach dem 32er-Lauf
  damit war der Host beendet (Ursache unbekannt, Log überschrieben). Streuung zwischen 32er-Läufen ~±10 %.
  Nach einem Host-Neustart fragt der Host die Mitgliederliste erst ~30–60 s nach dem Laden ab; früher gestartete
  Fake-Clients scheitern mit `InvalidCredential` (Messläufe warten auf das zweite `GET /dev/battle/members/`).
- **PPU-Profil des Game-Threads, 16 feuernde Fake-Clients gegen 0 (2026-10-30, `tools/ppu_profile.py`; noch mit falschen
  Level-Namen der Fake-Clients, der Level-Such-Hotspot ist ein Artefakt, siehe oben):** RPCS3-Option
  `PPU Profiler: true`, je Lauf Boot + ~160 s Gefecht, mit Clients davon ~130 s mit 16 feuernden Clients; Host über
  `CloseMainWindow` beendet (nur dann schreibt RPCS3 das Profil). Rohdaten in `research/profiles/prof_{0,16}.log`.
  main_thread: 112 450 → 161 977 Samples mit Gastcode (+49 527 ≈ 37 s von ~130 s), „idle“ (Wartezeit in Syscalls)
  64,5 % → 47,4 %. Größte Zuwächse (Anteil am Zuwachs der gelisteten Funktionen; das Profil listet nur die Spitze):
  - 18 % `0x5ea700` und verwandte `0x5ea664` (+1,3 %): nach Struktur `UNetConnection::ClientHasInitializedLevelFor`
    bzw. die Variante im PackageMap: läuft die Outer-Kette zum Level hoch und sucht dessen FName **linear** in
    `ClientVisibleLevelNames` (TArray<FName> bei Connection+0x5060/+0x5064; Persistent-Level-Name bei +0x5058). Pro
    Actor und Verbindung, bei ~168 gemeldeten Levels pro Client. Kandidat für einen Code-Höhlen-Patch (z. B. Treffer nach
    vorn tauschen; die Reihenfolge der Liste ist bedeutungslos).
  - 7 % `0x823498`: Gitter-/Octree-Abfrage (Koordinaten werden geshiftet, `0x82c154` prüft Boxen), vermutlich
    Kollisions-Hash oder Relevanz-Octree.
  - 4 % `0x11481f0` memmove, 3,8 % `0x1198304` TMap/TSet-FindId mit Pointer-Hash (z. B. Actor → Kanal),
    2,5 % `0x1197cd8`, 5,7 % `0x2b4768`, `0x2d5a5c`, `0x2d55a0` (noch nicht zugeordnet).
  Die Vermutung, ein großer Teil der Mehrkosten stecke in Syscalls (der Profiler zählt sie als „idle“), ist widerlegt,
  siehe nächster Fund. Das „idle“ im Profil stammt aus Ladephase und Leerlauf, nicht aus den Spielern.
- **Host-Thread auf Windows-Ebene gesampelt (2026-10-30, `tools/thread_sampler.py`, je ~1000 Samples/s):**

  | | CPU main_thread | JIT (Gastcode) | echtes Warten (ntdll Wait) | rpcs3.exe | Netz (DeviceIoControl) |
  |---|---|---|---|---|---|
  | Host allein, 15 s | 49 % | 43,5 % | 52,6 % | 3,6 % | 0,2 % |
  | 16 feuernde Clients, 30 s | 97 % | 85,6 % | 7,2 % | 5,3 % | 1,7 % |

  Die Mehrkosten pro Spieler sind fast ausschließlich Gastcode. sys_net und der übrige RPCS3-Kernel kosten zusammen
  unter 10 %. Ohne Clients wartet main_thread die Hälfte der Zeit (Bildtakt/RenderingThread), mit 16 Clients kaum noch.
  Folgerung: Hebel sind Patches am Gastcode (Octree/TMap; die Level-Suche war ein Artefakt) oder schnellere PPU-Ausführung
  (Recompiler), nicht RPCS3-Syscalls. Kernelzeit (21 %) ist größtenteils Overhead des Samplers (Suspend/Resume).
- **Heap im emulierten Speicher bei 16 und 32 Spielern (2026-10-30, `tools/vm_footprint.py`):** UE3 legt seinen Heap in einen
  `sys_vm`-Bereich (`sys_vm_memory_map vsize=0x10000000 psize=0x9200000` ab 0x40000000, also 256 MB virtuell, 146 MB physisch).
  RPCS3 hinterlegt die ganzen 256 MB, deshalb zeigen Prozess-RAM und Dumps nichts. Der Allokator meldet aber jede 64K-Seite
  mit `sys_vm_touch`/`sys_vm_invalidate` (im RPCS3.log); die Bilanz ist der belegte Heap. Messung im selben Host-Lauf wie
  die Tick-Reihe oben:

  | Zustand | Heap | frei bis 256 MB |
  |---|---|---|
  | Host allein im Gefecht | 140 MB | 116 MB |
  | 16 feuernde Fake-Clients | 171 MB | 85 MB |
  | 32 feuernde Fake-Clients | 213 MB (Spitze) | 43 MB |
  | alle wieder weg | 193 MB | 63 MB |

  Also ~2,0–2,3 MB pro Spieler; rechnerisch ist bei ~50 Spielern Schluss. Nach dem Verlassen bleiben ~50 MB belegt, bei
  Kommen und Gehen in einem langen Match wächst der Heap also weiter (Host-Neustart pro Match ist ohnehin geplant).
  `psize` (146 MB) überschreitet der Host schon allein; RPCS3 erzwingt das nicht (`sys_vm_get_statistics`, das der
  Game-Thread jeden Frame abfragt, meldet nichts belegt), auf echter Hardware würde ausgelagert. Der Kernel-Rest außerhalb
  des Heaps (`sys_memory_get_user_memory_size`) liegt bei 4–11 MB frei von 213 MB und wächst nicht mit Spielern
  (nur 14 `sys_memory_allocate`, alle beim Start). Für 32 Spieler ist der Speicher damit keine harte Grenze, der
  Game-Thread schon.
- **16 und 32 feuernde Fake-Clients (2026-10-30, frischer Host, alle mit Waffe; noch mit falschen Level-Namen, korrigierte
  Werte oben):** Host `D:\rpcs3` Null-Renderer, `-novsync`,
  Clients `--play --fitting assault --fire-interval 5 --fire-burst 2`, 30 s `host_tick.py`:

  | Clients | Ticks/s | Mittel / p95 / max (ms) | main_thread | RSS rpcs3 | Host-Pawns |
  |---|---|---|---|---|---|
  | 16 | 39,3 | 25,4 / 34,8 / 257 | 94,8 % | 2443 MB | 16 |
  | 32 | 16,6 | 60,3 / 81,8 / 116 | 95,4 % | 2446 MB | 31 |

  Engpass bleibt allein der Game-Thread (ein Kern voll), RAM des Prozesses wächst kaum. Bei 32 liegt der Host deutlich
  unter der konfigurierten Tickrate 30. Im 32er-Lauf starben 9 Clients und spawnten neu (41 Spawns für 32 Clients), der
  Respawn funktioniert also. Fake-Clients zusammen 117 % CPU (3,6 % je Client, 30 MB), verfälschen die Messung auf 24
  logischen CPUs kaum. Der frühere 16er-Wert (49 Ticks/s) war zu hoch, weil 6 Clients keine Waffe hatten (siehe nächster
  Fund).
- **Nur 100 Charakter-IDs haben Inventar (2026-10-30):** Der Host legt Inventar, Skills und Spawn-Fitting nur für CCPs
  Offline-Charaktere 2100001611–2100001710 an (`userBattle.OfflineConnect`, `NUM_OFFLINE_PLAYERS = 100`). Ab ID
  2100001711 wirft `fittingBattle2._CheckFittingValid` `'NoneType' object has no attribute 'current'` (Inventar fehlt), der
  Pawn spawnt ohne Waffe. Der CREST-Server zählte die IDs je Host-Sitzung nur hoch (jeder Fake-Client-Start = neue ID); im
  ersten 16er-Lauf mit Feuer bekamen deshalb nur 10 von 16 eine Waffe. Behoben: `register_listen_member` lässt die IDs im
  Bereich 2100001612–2100001710 umlaufen. Für mehr als 99 gleichzeitige Spieler müsste der Dev-Hook Inventar selbst anlegen.
- **Fake-Clients schießen (2026-10-30, Mitschnitt `dust_server/logs/udp_proxy_fire.jsonl`):** Ablauf nach `GivePawn`:
  `ServerSetCurrentWeapon(<Waffenkanal>)` auf dem eigenen `DustPawnInventoryManager` (Index 23 von 27), auf der
  `DustHandheldWeapon` `ServerSetCurrentFireMode(0)` (52/54); je Stoß auf Kanal 1 `ServerSetRightTriggerHeld(true)` (126)
  plus `ServerStartFire(FireModeNum, TimeStamp)` (26/54), beim Loslassen `ServerStopFire` (27/54) plus
  `ServerSetRightTriggerHeld(false)`; Nachladen `ServerReloadWeapon(0)` (157) auf Kanal 1. Alle Bunches bitgleich zur
  Aufnahme (Index-Breite hängt vom Wert ab: 26 von 54 = 5 Bit). Wirkung auf dem Host nur mit dem Assault-Fitting
  (Militia Assault Dropsuit 354941, Militia Assault Rifle 353120, `--fitting assault`): Magazin (`mAmmoInClip0` +0x848)
  56 → 29 je 2-s-Stoß, nach dem Nachladen wieder 56. Das aufgezeichnete Standard-Fitting trägt eine Aufladewaffe
  (siehe Ausprobiert). Inventar und Waffe öffnet der Host beim Spawn nur dem Besitzer; der Fake-Client nimmt den
  jeweils letzten Kanal dieses Archetyps.
- **Host-Last mit laufenden und schießenden Fake-Clients (2026-10-30, Stoß 2 s alle 5 s, Client b beendet):**

  | Fake-Clients | Ticks/s | Tick Mittel / p95 | main_thread | RSS |
  |---|---|---|---|---|
  | 0 | 87,8 | 11,4 / 17,8 ms | – | 1455 MB |
  | 1 | 86,9 | 11,5 / 17,6 ms | 75 % | 1456 MB |
  | 4 | 82,8 | 12,1 / 17,2 ms | 93 % | 1595 MB |
  | 8 | 60,7 | 16,5 / 23,8 ms | 94 % | 1595 MB |

  Gegen die Reihe ohne Feuern (85,3 / 75,4 / 69,7): bei 8 rund 9 Ticks/s weniger, bei 4 sogar mehr. Je ein Lauf, die
  Streuung liegt also bei mehreren Ticks/s; für belastbare Aussagen Läufe wiederholen. RSS diesmal ~1,5 GB statt 2,4 GB
  (anderer Zustand des Host-Prozesses nach dem Beenden von Client b, nicht untersucht).
- **Host-Last mit laufenden Fake-Clients (2026-10-30, `host_tick.py --log`, Host `D:\rpcs3` Null-Renderer, `-novsync`):**
  alle Fake-Clients gespawnt und laufend (~26 `ServerMove`/s je Client), Mittel über 30 s:

  | Fake-Clients | Ticks/s | Tick Mittel / p95 | main_thread | Prozess-CPU | RSS |
  |---|---|---|---|---|---|
  | 0 | 86,5 | 11,6 / 17,8 ms | 78 % | 497 % | 2425 MB |
  | 1 | 85,3 | 11,7 / 17,4 ms | 84 % | 499 % | 2433 MB |
  | 4 | 75,4 | 13,3 / 17,6 ms | 95 % | 500 % | 2436 MB |
  | 8 | 69,7 | 14,3 / 20,5 ms | 95 % | 498 % | 2438 MB |

  Game-Thread ab 4 Clients gesättigt, RAM praktisch konstant. Lineare Fortschreibung (~2 Ticks/s je Client) ergäbe bei 32
  Spielern noch ~20–30 Ticks/s, muss gemessen werden. Ohne Waffenfeuer. Erste Messung vor dem Empfangs-Fix (Fake-Clients
  sendeten bei 8 nur ~45 % der Moves) lag bei 64,3 Ticks/s für 8, also ist Move-Last messbar.
- **Fake-Client spawnt und läuft (2026-10-30):** nötiger Ablauf (nach Join):
  1. `ServerUpdateLevelVisibility(PackageName, true)` für alle sichtbaren Level, sonst trennt der Host bald. Namen gehen über
     einen Name-Cache je Richtung: erste Nutzung = Cache-ID (ab 0x401) + String + FName-Nummer, danach nur −ID. Level:
     Karten-Level mit `bNewShouldBeVisible` aus `ClientUpdateLevelStreamingStatus` (+ `_MT`, `_VI`), das `MOOD_`-Level
     (Nummer = dessen Kanal) und je Struktur-Socket `<Struktur>_LOD0`, Nummer = Actor-Kanal des Sockets (Socket-Open nennt
     `small07`/`OP03`/`BackDrop01` und dann die Struktur), Backdrops ohne `_LOD0`. Ein Replay der aufgezeichneten Namen
     scheitert deshalb (andere Kanäle → Host trennt).
  2. `InvokeSvcMethodOnBattleServer(battleServer, SpawnCharacterWithFitting, …)`, dann im selben Moment
     `ServerSelectDefaultSpawnPoint` (Index 26 von 38) auf dem eigenen `DustControllerSharedComponent`-Kanal und
     `ServerBeginSpawnProcess`. Ohne Spawnpunkt bricht `Dead.CheckSpawnPointIsValid` ab (`ClientNotifySpawnPointCancelled`).
  3. Host: `InvokeSvcMethodOnClient` (Bestätigung), `ClientSetTimeLeftBeforeRespawn(~4,9 s)` + `ClientStartCheckStreaming(loc)`.
     Client setzt `ClientLoc` auf `loc`, meldet `<Struktur>` und `<Struktur>+AU` sichtbar und schickt
     `ServerOnStreamingFinished` (setzt `mClientReadyToSpawn`; echter Client packte es hinter ein `ServerMove`).
  4. Nach dem Timer `Dead.DoRestartPlayer`: `ClientPreRestartPlayer` → Ack(None) + `AskForPawn` → `GivePawn` → Ack(Pawn).
     Pawn nach ~9 s, `ServerMove` bewegt ihn (pawn_list: 600–1100 uu je 3 s). Position folgt den `*ClientAdjustPosition`.
  Bugfix: `BitWriter.serialize_int` im Fake-Client brach mit `value + mask` statt den geschriebenen Bits ab, Längen ≥ 2048 Bit
  waren kaputt (wohl auch Ursache früherer Replay-Abbrüche). msg 20 ist eine Name-Cache-Bestätigung (−ID), nicht nötig.
- **Fake-Client-Prototyp tritt bei (2026-10-30, `tools/fake_client.py`):** Registriert ein Mitglied über den neuen Dev-Endpunkt
  `POST /dev/battle/fake_member/` (gleiche Teamverteilung wie echte Beitritte), dann Hello → Challenge → Login (Antwort `"0"`,
  URL mit Credential) → Welcome → Join, danach nur Acks und Keepalive (alle 50 ms). Hello, Login und Join sind bitgenau gleich
  mit dem aufgezeichneten echten Client. Fallen dabei: `bControl` heißt „Open-/Close-Flags folgen“ (nur im ersten Bunch),
  nicht „Control-Channel“; der Host lehnt mit `Engine.AccessControl.InvalidCredential` ab, solange sein Dev-Hook die
  Mitgliederliste noch nicht abgefragt hat (Poll alle 3 s, beginnt erst einige Sekunden nach dem Laden der Karte), daher
  Neuversuch. Ergebnis: Host zählt den Fake-Client als Spieler, hält ihn ohne Kick (70 s getestet), öffnet ihm 71–76
  Actor-Channels und schickt ~9 Pakete/s (ungespawnt). msg 20 muss der Client dafür nicht senden. 5 Fake-Clients
  gleichzeitig: Host 6 Spieler, 87,8 Ticks/s; je Fake-Client ~0,8 % eines Kerns, 27 MB RAM (RPCS3-Client: ≥ 2 Kerne,
  2,4 GB). Noch nicht: Spawn, Bewegung, Feuern (RPCs auf dem PlayerController-Kanal 1); ungespawnte Spieler kickt der
  Chess-Timer nach 7–8 min.
- **Fake-Client machbar: Gefechtsverkehr ist unverschlüsseltes Standard-UE3 (2026-10-30):** Mitschnitt mit `tools/udp_proxy.py`
  (`fake_battle.json` `target_listen.port` vorübergehend auf 17778, Proxy leitet an 7777 weiter; Log
  `dust_server/logs/udp_proxy.jsonl`), Auswertung mit `tools/ue3_packets.py`. Client e (Null-Renderer): Login, Spawn, Laufen.
  - Alle 17.785 Pakete zerlegen sich mit dem Standard-Paketaufbau aus `UNetConnection::ReceivedPacket` (Bitstrom LSB-first,
    PacketId 14 Bit, Acks pro Paket, Bunch-Header, MaxPacket 512). Keine Verschlüsselung, keine Kompression. Klartext sichtbar:
    Login-URL, Klassen-/Archetyp-Namen (`UPackageMapSeekFree`: Objekte über Namen, kein GUID-Abgleich), Teamnamen.
  - Handshake (Kanal 0, Big-Endian-Ints): Client Hello (msg 0, Konstanten, wörtlich kopierbar) → Host Challenge (msg 3,
    `87C55F50`) → Client Login (msg 4: NetSpeed 20000, Challenge-Antwort nur `"0"`, URL
    `:<port>/LoginScene?credential=…?Team=0?…?Name=DustPlayer?SeekFreeLoading=1?Version=2.13.0.249`) → Host Welcome (msg 11:
    `MN_CRATERS01`, `DustGame.DustSkirmishGame`) → Client msg 9 (wohl Join). Danach in beide Richtungen viele msg 20 mit
    fortlaufenden negativen IDs (`fffffbff`, `fffffbfe` …), vermutlich CCPs `NetObjConfirm` (Namen `NetObjConfirm`,
    `NetObjRemoteDestroy`, `PktSim` stehen in der NMT-Namensliste des EBOOT).
  - Last pro Client (1 Spieler, gespawnt, kurz gelaufen): je Richtung ~55 Pakete/s, ~1–1,4 kB/s. Kanal 1 (Actor, vermutlich
    PlayerController) trägt fast alles; der Host öffnet 297 Actor-Channels für einen Client.
  - Offen für einen Fake-Client: Bedeutung von msg 20 (muss der Client Objekte bestätigen?), Actor-Channel des eigenen
    PlayerControllers erkennen, RPC-Kodierung von `ServerMove`, Spawn (Smart Deploy) und Feuern (Funktions-Index im
    Bunch, gepackte Parameter). Credential kann der eigene CREST-Server direkt ausstellen (`register_listen_member`).
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
  - **Erster RPCS3-Test (2026-10-30, DustTester2 auf 8081, FinstererFred als Host-Konto auf 8080):** Die Charakterauswahl zeigt den
    eigenen Charakter (25 000 ISK, 500 000 SP, Amarr Templars). Der Skill-Bildschirm zeigt die 8 Start-Skills und die richtigen freien SP.
    Upgrade 353435 von Stufe 1 auf 2 ohne Trennung, freie SP 363 170 → 344 520 (−18 650). Einziger 404 ist das Corp-Logo
    (`/images/corporations/…_64.png`, schon immer). `KeyError` 'location'/'fulfillments' in `entitlementsClient` gab es auch vorher.
    Live-Update aus dem Admin bestätigt: Stufe zurück auf 1, Client bekommt `OnCharacterSkillChangeFromBackend` und zeigt es sofort.
    Skillbuch bestätigt: In Assets → Skills ✕ auf ein Buch mit grünem Haken → „Use Skillbook“ (nur für unbekannte Skills mit
    erfüllten Voraussetzungen). Amarr Light Dropsuits 364570 steht danach auf Stufe 0, die SP bleiben gleich.
    Charakterblatt: `myCharactersClient.GetPortrait` wirft `KeyError: 'portrait'`, weil unser `/characters/{id}/` kein `portrait`
    hat. Fix: `"portrait": None` → Standardporträt, in RPCS3 geprüft (Charakterblatt ohne Fehler).
    Neu-Login nach Server-Neustart bestätigt: Stufen, Skillbuch (L0) und freie SP (363 170) bleiben erhalten. Außerdem `IndexError` in
    `dropsuitProgression.UpdateAvatarView` (`AVATAR_ICON_DATA[frame][race]`). Die Seite war vorher nie offen, wahrscheinlich ein Client-Fehler
    bei einem vierten Frame-Reiter. Noch nicht untersucht.
    Ablehnung: Bei zu wenig SP blockt schon der Client (`uiSvcSkill.CallBackGetPopUpForUpgrade` zeigt „not enough skill points“,
    kein `PUT`). Die serverseitige Ablehnung ist also nur im Prozess getestet, ein normaler Spieler erreicht sie nicht.
    Passiver Zuwachs bestätigt: Aktivieren in der Auswahl → `PUT …/passiveskillgain/{id}/ {status: 1}`, „ACTIVE“. Danach steigt die SP-Anzeige
    1 SP pro 3,6 s (24 000/Tag), Client und Server liegen nach einigen Minuten gleich.
    Noch offen: `IndexError` Dropsuit-Progression.
  - **Respec (2026-10-30):** Im Client nur über das Item 367499 „Skill Tree Reset and Refund“ erreichbar (`inventory2`: Assets → Item →
    „Reset Skills“, oder `purchasePopup` nach dem Kauf). Kein Menüpunkt im Skill-Bildschirm. Der Client liest
    `mercenaryPublicData['respec']['href']`, den CCPs Offline-Daten nicht haben (KeyError). Laut Item-Text: Skills zurück,
    SP erstattet, Corp-Skills bleiben, Skillbücher zu 80 % des Marktpreises erstattet. Umgesetzt als Rückkehr zu den Start-Skills
    plus Corp-Skills, ISK-Gutschrift. Im Prozess geprüft (Amarr Light Dropsuits → 183 200 ISK), in RPCS3 noch offen.
- **Stufe 3 (2026-10-30), hinter dem Schalter:** Erstellen und Löschen von Charakteren. Funde aus dem Client-Code:
  - Erstellen schickt nur `{name: "<Vorname> <Nachname>", gender, bloodline: href}`. Rasse, Spezialisierung und Porträt folgen aus der
    Blutlinie. Die Root-Links heißen `bloodlines`, `dustSpecialties`, `dustPortraits`. Der Client vergleicht `race.href` der Blutlinien
    mit den Hrefs aus `GET /races/` (CCPs Offline-Daten).
  - 403 mit `{title, message}` zeigt der Client als Popup und springt zurück zur Namenseingabe. Bei 200 geht es zur Auswahl.
  - Löschen: `POST <self> {prepareDelete: true|false}`, die Liste zeigt `deletePrepareDate` (UTC), danach `DELETE <self>`.
  - CCPs Offline-Handler liefert für jede Corp-ID „Amarr Templars“. Mit Schalter setzen wir für 1000214 „Seituoda Taskforce Command“
    und für 1000216 „Crux Special Tasks Group“ ein (Namen aus den Offline-Charakteren 2 und 3).
  - Im Prozess geprüft (Wegwerf-DB): Stammdaten, Erstellen, Ablehnungen (Name doppelt/zu kurz, vierter Charakter, Löschen zu früh),
    Countdown, Abbrechen, Löschen, Name danach wieder frei. Parität ohne Schalter unverändert.
  - **RPCS3 (DustTester2):** Stammdaten werden geladen (`/races/`, `/bloodlines/`, `/specialties/`, `/portraits/mercenary/`), ein
    vergebener Name gibt das Popup (403), Anlegen klappt (2100100001, Vherokior). Wählen und Laden in die Quarters ohne neue Fehler.
    Ohne Familienname schickt der Client `"name "` mit Leerzeichen am Ende, das wird bereinigt. Löschen bestätigt: Terminate →
    `POST {prepareDelete: true}`, Countdown 60 s, dann `DELETE` → 200, der Platz ist wieder leer (`deleted = 1`), keine Client-Fehler.
    Abbrechen bestätigt (`prepareDelete: false` setzt den Countdown zurück, erneutes Terminate startet ihn neu).
  - **Start-Corps je Rasse (2026-10-30):** CATMA-Typ `starting_corporations_global` (356418) listet je 12 NPC-Corps pro Rasse
    (`amarrCorporations.0–11` usw.). Amarr 1000205–1000207 und 1000223–1000231, Caldari 1000208, 1000213, 1000214 und
    1000232–1000240, Gallente 1000215–1000217, 1000222 und 1000243–1000250, Minmatar 1000218–1000220 und 1000251–1000259.
    Die Offline-Corps stehen jeweils in der Liste ihrer Rasse (1000205 Index 0, 1000214 Index 9, 1000216 Index 3). Der Client-Code
    nutzt die Liste nicht (die Zuteilung machte CCPs Backend). Namen stehen im Client nur für die drei Offline-Corps. Weder
    die String-Caches noch ADAPTERDATA/MODULEDATA enthalten Corp-Namen. Die öffentliche ESI liefert alle 48
    (`POST https://esi.evetech.net/latest/universe/names/`), jetzt in `characters.STARTING_CORPORATIONS`. Die CATMA-Reihenfolge
    ist alphabetisch nach Namen. Minmatar-Charaktere kommen zu 1000251 Brutor Vanguard. In RPCS3 bestätigt (Brutor-Charakter
    2100100003, Anlegen, Login und Corp-Seiten ohne Fehler). Schönheitsfehler: Das Mitgliedsdokument
    `/corporations/1000251/members/{id}/` kommt von CCPs Offline-Handler und verlinkt die Rollen unter 1000205.
    Noch offen: erster Login eines neuen Kontos ohne Charakter (drei leere Plätze).

- **Stufe 4, echte Skills im Gefecht (2026-10-30), hinter dem Schalter:** Beim Beitritt (`POST /battles/{id}/members/`) mit
  eigenem Charakter liefert `/dev/battle/members/` zusätzlich Name, Rasse, Corp, Geschlecht, `crestCharacterID` und
  `skills: [[typeID, level], …]`. Der Dev-Hook des Hosts setzt `skillBattle.knownSkills[ID]` und ruft `_UpdateDataCache` (→
  `_pystims.UpdateSkills`), Log „skills updated for character“. Funde im Client-Code:
  - `userBattle.OfflineConnect` setzt für die 100 Offline-IDs alle Skills auf 5, legt aber nur einen **leeren**
    `skillDataCache` an und ruft `_pystims.UpdateSkills` nie. Fitting-Prüfung (`CharacterHasSkillsForTypeUE3`) sieht also
    Stufe 5, die Werte-Berechnung (`ue3Context.GetRelevantSkills`) keine Skills. Bisher kämpfte also jeder ohne Skill-Boni.
  - Gefechts-IDs laufen um. Ein späteres Mitglied ohne Skills auf derselben ID bekommt den `OfflineConnect`-Stand zurück.
  Im Prozess geprüft (Wegwerf-DB, Minmatar-Charakter: 8 Start-Skills, Brutor Vanguard; fremder Token und Offline-ID → keine
  Skills), Hook mit py27 kompiliert, `COMMON.SDAT` von `D:\rpcs3` neu gepatcht.
  **RPCS3 (2026-10-30, Host A + Client B, DustTester2 mit „212“, Minmatar, nur Start-Skills):** Host meldet
  `skills updated for character 2100001613 (212): 8 skills`. Spawn mit Militia-Fitting (354941 Dropsuit, 353120 Gewehr,
  368949) geht durch `_CheckFittingValid` (prüft gegen `skillBattle.GetKnownSkills`, also die echten Skills). Gegenprobe mit
  einem Fitting ohne passende Skills ist für einen normalen Spieler nicht erreichbar, der Client bietet nur gültige Fittings an.
  **Falle:** Mit `-autologinserver` setzt der Client `skipPSN` (`login.py`) und meldet sich mit Benutzername und Passwort an,
  also ohne RPCN-Ticket → gemeinsamer Offline-Token, Offline-Charaktere. Tests mit eigenen Charakteren nur ohne Autologin.
  Offen: Schild/Panzerung im Gefecht mit Skill-Boni vergleichen. Docker: `export_host_data.ps1` erneut ausführen.
- **Stufe 5a, Inventar, Fittings und Käufe pro Charakter (2026-10-30), hinter dem Schalter:** Ausgangslage im RPCS3-Test:
  Kauf im ISK-Markt (Warbarge Component, 10 ISK) → `POST /market/10000001/orders/buy/` 404 → Popup „Requested item not
  found on the market“; Kaufen ging also nie. Umsetzung und Formate siehe `docs/character_server_plan.md` („Umsetzung
  Stufe 5a“). Funde aus dem Client-Code:
  - Das Kauf-Popup (`purchasePopup._BuyItem`) wartet in einer Schleife auf `OnPersonalInventoryChangedNotification` mit
    dem gekauften Typ. Ohne `OnItemsChanged` vom Server hängt es.
  - VGS-Kauf: Eine nicht leere Antwort auf `POST /sales/` wertet das Popup als Fehler („PurchaseFailed“). CCPs
    Offline-Handler antwortet `{}`.
  - Neue Fittings scheiterten bisher am Lokalisierungsdienst (`GetDisplayNameByID`), jetzt nicht mehr über CCPs Handler.
  - Respec: Der Client benutzt das Item nicht selbst (`inventory2` ruft direkt `CallbackRespec`), der Server verbraucht es.
  Im Prozess geprüft (Wegwerf-DB, zweiter CATMA-Dienst auf 8091): 24 Start-Items, 11 Start-Fittings, Fitting anlegen,
  kopieren, Slot setzen/leeren, umbenennen, löschen, fremdes Fitting 404; ISK-Kauf mit Benachrichtigungen, zu wenig ISK
  403, unbekannter Typ 404; AUR-Kauf 1000 → 975, Betrag falsch 409; LP-Kauf 5000 → 1000 plus ISK, zu wenig LP 403;
  Respec verbraucht das Item; Skillbuch ohne Item abgelehnt, mit Item gelernt und verbraucht. Parität ohne Schalter
  identisch (26 Anfragen).
  **RPCS3 (2026-10-30, Client b, DustTester2, eigener Charakter):** ISK-Käufe gehen (Popup schließt, Inventar aktualisiert).
  Neues Fitting im Fitting-Menü trennte zuerst: leere Slots kamen als `module: {id: None}`, `fitting._InitSlotsInfo` setzt
  nur bei fehlendem Schlüssel `TYPEID_NONE` (-1), `None` → `stims.FitModule` RuntimeError (auch beim Spawn über
  `GetDefaultFittingString`). Fix: leere Slots ohne `module`, Slots ohne Standard ohne `defaultModule`. Danach neues
  Dropsuit-Fitting angelegt, ohne Fehler. Folge: Ein Slot mit Standardmodul lässt sich nicht leeren (der Client setzt
  dann das Standardmodul). AUR-Kauf bestätigt (DustTester2 per DB auf 5000 AUR, 356040 für 1280 AUR, Stand 3720,
  Popup schließt). Ohne eigenen Wert gilt `wallet.json` (Standard 0 AUR), dann blockt schon der Client („insufficient
  AUR“). Gefecht bestätigt (Host neu, Client b): `SpawnCharacterWithFitting 2100001612 364745:-1+-1,354106+354106,…`,
  der Host checkt das Fitting aus (`fittingBattle2 Checking out fitting`), danach keine Fehler, Spawn laut Nutzer ok.
  Leere Slots kommen als `-1` an. Der Host prüft weiter gegen sein 999er-Inventar und bucht nichts ab.
  Noch offen in RPCS3: LP-Kauf, Skillbuch/Respec verbrauchen.
- **Stufe 5b Matchende und Belohnungen, in RPCS3 abgenommen (2026-10-30/31, Details am Ende dieses Eintrags):** Funde im Client-Code:
  CCPs `_CompleteBattle` würde auf dem Listen-Host scheitern (`self.members` leer, `self.battle` None) und am Ende den
  Prozess beenden (`os.kill`). Der Ergebnisbildschirm (`endOfMatch2`) öffnet erst, wenn `dustClient.OnEndOfMatchResults`
  ankommt; „Merc Quarters“ darin ruft `dustUnreal.QuitToMercQuarters` (Rückkehr geht also clientseitig). Der Host hat die
  Client-Rolle, daher `inventoryBattle.useInventory = False`: `consumed` bleibt immer leer. `fittingBattle2` merkt sich
  ausgecheckte Fittings trotzdem (`checkedOutFittingString`), `DestroyFitting` entfernt sie beim Tod. UE3 ruft
  `@UnrealCallable`-Methoden über `svcmgr._methodRegistry` (beim Laden der Klasse gefüllt), Patches müssen dort mit rein.
  Umsetzung: `dustdevhook` ersetzt auf dem Listen-Host `_CompleteBattle`/`_MemberLeftBattle`, zählt Verluste in
  `DestroyFitting` (verbrauchbar → consumed, sonst nonConsumed) und Spielzeit ab `OnBattleMemberJoinedFromUnreal`, schickt
  `POST /dev/battle/completed/` bzw. `/dev/battle/members/{id}/completed/` (nur vom Host) und verteilt die Antwort als
  `OnEndOfMatchResults` (eigener Spieler des Hosts direkt). Server: Tabelle `battle_members` (Schema 3, Schlüssel
  Credential), Buchung in einer Transaktion, Formel und Wochengrenze (Montag 00:00 UTC) in `content/rewards.json` „battle“
  (Web-Admin „Rewards“). Wer früher geht, bekommt nichts, verliert aber Ausrüstung. Im Prozess geprüft (Wegwerf-DB): 403
  von außen, Sieg 900 WP → +1400 SP/+145000 ISK, Verlust auf Bestand begrenzt, doppelte Meldung ignoriert, Abgang bucht
  nur Verluste. Parität ohne Schalter identisch.
  **Offen in RPCS3:** Ruft der Host `OnBattleServerStoppedFromUnreal` überhaupt auf? Kommt `DestroyFitting` beim Tod?
  Welche Felder hat `GetEndOfMatchPlayerInfoList()` (wird geloggt)? Kommt `OnEndOfMatchResults` per
  `InvokeSvcMethodOnClientAsync` beim Client an? Vorher `patch_common_sdat.py` für Host und Client b ausführen und den
  CREST-Server neu starten (Schema-Migration 3 legt `dust.sqlite.bak-2` an).
  **Eingespielt (2026-10-30, Host):** Erster Start scheiterte: `import svcmgr` gibt es im Spiel nicht (Modul heißt
  `dust.svcmgr`, CCPs Code importiert es implizit relativ). Weil der Patch beim Import von `dust.fittingBattle2` lief,
  fehlten danach alle Gefechtsdienste (`userBattle` not found). Fix: Registry über
  `module.UnrealCallableClass.func_globals` holen, Patch-Fehler fangen (`_ApplyPatch`). Danach alle drei Patches aktiv.
  **Abgang vor Matchende in RPCS3 bestätigt (2026-10-30, Client b, Charakter 2100100003, Skirmish):** Tod über das Menü →
  `DestroyFitting` kommt, Hook zählt `{367456: 1}` (nur der Dropsuit; `GetRequiredItems` verlangt für dieses Fitting keine
  Module, vermutlich Standardmodule). Spiel verlassen → `_MemberLeftBattle` → `POST /dev/battle/members/2100001612/completed/`
  (Dauer 158 s) → Server bucht 0 SP/0 ISK und zieht 367456 ×1 ab, Zeile in `battle_members` mit `completed_at`.
  Migration 3 lief (`dust.sqlite.bak-2`). Offen: Matchende mit Ergebnisbildschirm (braucht ein zu Ende gespieltes Match).
  **Matchende per `SetWinner 1 0` (Dev-Controller → `DustTeamGame.SetWinner`):** Der Listen-Host ruft
  `OnBattleServerStoppedFromUnreal (1, 2, 2)` auf (Sieger, Klonverluste Angreifer/Verteidiger) und öffnet `matchResult`.
  Zweiter falscher Import (`from svcmgr import GetUnrealService`) → unbehandelte Ausnahme, Host vom Netz getrennt. Fix:
  `svcmgr` aus dem Modul von `battleServer`, Matchende komplett in try/except, Abgänge aus der Mitgliederliste nehmen.
  Der zweite Beitritt von 2100100003 (Credential ungebucht) verlor dadurch nichts.
  **Matchende in RPCS3 bestätigt (2026-10-30, zweiter Lauf):** `SetWinner 1 0` → `OnBattleServerStoppedFromUnreal` →
  `GetEndOfMatchPlayerInfoList()` liefert `[{'characteruri', 'warpoints'}]` je Spieler (auch der Host) →
  `POST /dev/battle/completed/` → Buchung (hier 0 SP/0 ISK: nur ~15 s im Gefecht, `min_seconds` 60) →
  `OnEndOfMatchResults` per `InvokeSvcMethodOnClientAsync` kommt an, Client b öffnet `endOfMatch2`. Klonverluste 0/0
  (keine Tode). Beim Host-Spieler fehlte `dustClient.endOfMatchResults` (wird nur beim Beitritt gesetzt), Hook legt es
  jetzt an (beim nächsten Host-Start aktiv). Offen: Belohnung > 0 mit Spielzeit ≥ 60 s, Rückkehr in die Merc Quarters.
  **Stufe 5b abgenommen (2026-10-31, dritter Lauf, 123 s, ein Tod, `SetWinner 1 0`):** Klone 0/1, Buchung „won: 0 WP,
  +500 SP, +100000 ISK, lost {367456: 1}“, Charakter 2100100003 danach 500 500 SP / 105 380 ISK. `endOfMatch2` auf
  Client b und beim Host-Spieler, „To Merc Quarters“ → `QuitToMercQuarters` → zurück im Quartier. War Points blieben 0
  (keine Gegner); Formel mit WP > 0 ungetestet. Ungebuchte Zeile vom abgestürzten zweiten Lauf bleibt in `battle_members`.

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
- **Pop-in am Vulkan-Client (2026-11-01, Screenshots des Nutzers):** (a) An manchen Stellen springen Felsen/Dünen im Stand
  zwischen zwei Formen (Proxy `X_LOD0_n` ↔ Detail). Vermutlich die Überblendung im Client (`FUN_0099ac80`) ohne
  ausreichende Hysterese genau an der Distanzschwelle, also dieselbe Mechanik wie bei der LOD-Kollision, nur beim Rendern.
  Kein echtes Z-Fighting (dann würde es pro Pixel flimmern, nicht ganze Formen tauschen). (b) Berg nur teilweise scharf und
  nach Drehen komplett: Terrain-Kacheln (`FUN_007fb450`) bzw. Textur-Streaming lädt nur, was im Sichtkegel liegt. Mögliche
  Verstärker: EdgeZlib-Bypass (Entpacken synchron auf der PPU statt SPU) bremst das Streaming. Offen: Wie stark war das schon
  auf der echten PS3 (Dust war für Pop-in bekannt)? Erste Tests am Client, je einzeln: `Anisotropic Filter Override: 16`
  (verwaschener Boden), Host-Patch „load all outpost LODs“ auf dem Client, danach Schwelle/Hysterese in `FUN_0099ac80` suchen.

## Ausprobiert

- **RPCS3-PPU-Optionen am Host, 32 feuernde Clients (2026-10-30, je ein Lauf, Basis 18,5–21,3 Ticks/s):** `PPU Vector NaN
  Handling: false` 20,1 / 20,6 (kein Effekt), `Set DAZ and FTZ: true` 19,9 / 17,4 (kein Effekt bis schlechter),
  `HLE lwmutex: true` 17,8 / 16,8 (eher schlechter). Alle zurückgenommen. Nur der Scheduler half (siehe Funde).

- **Feuern mit dem Standard-Fitting (Aufladewaffe) zeigt keine Wirkung (2026-10-30):** Mit dem aufgezeichneten Fitting
  (Amarr Heavy Frame 352592, Waffe 368557, Magazin 4) lädt der Host die Waffe des Fake-Clients auf (`m_fCurrentCharge`
  +0x938 steigt in ~1 s auf 1,0, beim Loslassen `m_fCachedCharge` +0x93c = Ladung, d. h. `Charging.Fire_Internal` →
  `SendToFiringState`), aber Magazin bleibt voll und `ClientHandleExplosion` (142) kommt nicht; beim echten Client sank
  das Magazin 4 → 3 und 142 kam 160 ms nach dem Loslassen. Auch mit kopiertem `ServerRefreshCachedViewportInfo` nicht.
  Ursache offen, umgangen über das Assault-Fitting (siehe Funde). `Pawn.FlashCount` taugt nicht als Schussnachweis
  (blieb auch beim echten Schuss 0); Magazin (`mAmmoInClip0` +0x848) schon. Falscher Weg vorher: `PendingFire` (+0x1e8)
  bleibt bei Aufladewaffen immer 0, `DustWeapon.BeginFire` geht dort in den Zustand `Charging`.

- **`Frame limit: 30` am Null-Client (2026-10-30, `D:\rpcs3_e`, Backup `*.before_frame30`):** Unbrauchbar. Login extrem langsam
  (~25 s zwischen CREST-Anfragen, nach 10 min erst bei `/accounts/`), danach Stillstand ohne tickende Welt. V-Drücke während
  des Logins könnten mitgewirkt haben, wahrscheinlich ist aber das gleiche Flip-Schlafen wie bei `Auto`. Zurück auf
  `PS3 Native`: Beitritt nach 61 s, Spawn sofort. Ein niedrigeres Limit hätte ohnehin wenig gebracht, weil die Threads aktiv
  warten (VSync 60 statt 86 Hz sparte keine CPU).
- **`Frame limit: Auto` am Windows-Host (2026-10-30):** Host kam nur extrem langsam hoch (12–60 s zwischen den Login-Anfragen).
  Bekannt: ohne den eigenen RPCS3-Build schläft der Null-Renderer bei Auto an jedem Flip (`handle_emu_flip`). Zurück auf
  `PS3 Native`. `Vblank Rate: 120` hob die 60er-Grenze ebenfalls nicht (VSync wartet im Spiel), zurückgenommen.

- **`restart_all` mit Null-Renderer-Host (2026-10-30):** Der Host blieb zweimal vor der Charakterauswahl hängen (nach
  `/dust/asset/bundle/offline` nur noch Keepalives). Nur den Host neu zu starten (`restart_host.ps1`) half jedes Mal. Für den
  Watchdog wichtig: Ursache offen.

## Offene Fragen

- **Skirmish: gegnerisches MCC nimmt keinen Schaden (2026-11-01, Nutzer, alle Ziele > 10 min gehalten):** UnrealScript
  (`DUSTGAME.XXX`): Der Schadensweg im Script ist vollständig. `NceVehicleMCC.TakeDamage` → `m_pVIC.AbsorbDamage`,
  Meldungen bei 50/10 % Schild bzw. Panzerung, bei 0 HP Zustand `Dead` und `NotifyMCCDestroy`, sonst
  `DustSkirmishGame.OnMccDamaged` (Stufenwechsel bei < 50 % Leben). Der Schaden kommt von `DustAntiMccMissile`.
  Die Rakete sucht sich in `Ignite` das gegnerische MCC aus `svcContextor.mVehicles`, Flug per `ArmMissile`/`Homing`. Wer
  sie startet, steht nicht im Script: Spawn und Start sind nativ (Namen `InstallationGroup_AntiMCC`,
  `ConsoleGroup_AntiMccControl`, `antiMccConsoleTypeID`, `Installation_Missile`, `TickMissile`, `mMissileSocketID`), also
  die von den Zielkonsolen gesteuerten Anti-MCC-Installationen. Klassenname `DustAntiMccMissile` (UTF-16 0x1837ec2) wird
  nur in der Klassenregistrierung bei 0x7a9d24 referenziert. `DustAIMccTurretController` gehört zu den Geschützen auf
  dem MCC (`MCCTurretInfo.SocketName`), nicht zu den Zielen. Hypothese: Der Start der Rakete hängt an im Release
  entfernter KI bzw. an einem Stub (vgl. RDV-Dropship), oder die Installationen fehlen auf dem Host. Dev-Befehl
  `DamageMcc <team> <schaden>` → `ServerDamageMcc` ruft `TakeDamage` direkt (friendlyFireScale kurz 1.0), umgeht also den
  Raketenweg. Nächste Schritte: (1) `DamageMcc` testen: Sinkt die Leiste, fällt das MCC, endet das Match? (2) Feuern
  unbemannte Geschütze auf Gegner? (3) Abbild: Gibt es Anti-MCC-Installationen in der PawnList bzw. im Level, in welchem
  Zustand? (4) In Ghidra den Spawn der Rakete finden (Aufrufer der Klassenregistrierung bzw. `StaticClass`-Global).
  **`DamageMcc` wirkt (2026-11-01, Abbild `…_20261101_102034_live`):** Nach `DamageMcc 1 5000` und `DamageMcc 0 5000`
  (per `dev_once.py`, im Log `RunUE3Command`) haben beide MCCs (`NceVehicleMCC_0` Team 0 @0x47c387c0, `_1` Team 1
  @0x47c3c880) im VIC (`NceVehicle.m_pVIC` +0xb4c) Schild 1 143 000 (`DustVIC.mShield` +0x1f0) und Panzerung 1 148 000
  (`mArmor` +0x1ec), also je 5000 vom Schild abgezogen; voll vermutlich je 1 148 000. Pawn.Health ist bei MCCs nur 10.
  5000 sind 0,2 %, daher im Spiel unsichtbar. Folgerungen: Der Schadensweg bis zum VIC funktioniert. In über 10 Minuten
  mit allen Zielen kam außer den 5000 kein Schaden an, die Anti-MCC-Raketen feuern also wirklich nicht.
  **Matchende über zerstörtes MCC sauber (2026-11-01 10:24):** `DamageMcc 1 1000000` mehrfach → MCC zerstört →
  `OnBattleServerStoppedFromUnreal (0, 2, 0)` → `matchResult` → `POST /dev/battle/completed/` (9 Mitglieder, darunter
  alte Fake-Client-Einträge mit Dauer 0, die nichts bekommen) → `OnEndOfMatchResults` → Client b „To Merc Quarters“.
  **Erste Buchung mit War Points > 0:** 2100001619 (Client b) 574 WP → 1074 SP, 128 700 ISK. Danach bleibt der Host
  in der beendeten Karte stehen, pollt weiter `/dev/commands/` und startet **kein** neues Match. Neustart pro Match
  (CLAUDE.md Schritt 6) fehlt noch: unter Windows `tools/restart_host.ps1`, im Docker `control/restart`.
  **Raketenstart (Ghidra, 2026-11-01):** Die Klassen-Variable von `ADustAntiMccMissile` liegt bei 0x1cbde7c (gesetzt in
  0x71cdd4); alle Lesestellen liegen im eigenen Code der Klasse (0x7a9e9c–0x7aa004), kein Spawner nutzt sie. Die Rakete
  ist also Projektil einer Waffe, abgefeuert von den Anti-MCC-Installationen (Konsole hackt → `mSlaves.OnConsoleHacked`).
  Unbemannte Geschütze steuert `DustAITurretController` (Objekt 0x378, Verhalten `ShootAtTarget` 0xa0); ob das wie beim
  RDV im Release leer ist, ist offen. Python kennt die Zielbesitzer nicht direkt, aber `DustDataLog` schreibt
  `Hack`-Einträge (`actorID`, `teamID`, `isMissionObjective`) und `EntityTeamSwitch`; auf dem Listen-Host liest sie
  niemand (`dataLogBattle.SetMatchInfo` wird nie gerufen).
  **Ersatz im Dev-Hook (ungetestet):** `_MccBarrage` liest alle 10 s diese Einträge, führt die Besitzer der Ziele und
  ruft `DamageMcc <team> <n × 10000>` für jedes Ziel, das das andere Team hält (alle 4 Ziele: MCC nach ~9,5 min weg).
  Offen: ob `DustDataLog.IsEnabled()` auf dem Host wahr ist (sonst keine Einträge) und ob `teamID` 0/1 wie bei `DamageMcc`.
  Eingespielt 10:41 (Host-SDAT, Sicherung `COMMON.SDAT.before_barrage`; Client b nicht, der Hook betrifft nur den
  Host). Server mit `DUST_CHAR_STORE=1` über `restart_all.ps1 -ServerOnly` neu, Logs in `archive/20261101_104109_barrage`.
  Host meldet `objectives held by team 0/1: 0/0`, die Schleife läuft fehlerfrei.
  **Erster Hack ohne Eintrag:** `DustDataLog.IsEnabled` ist `NetMode == 1` (Dedicated), der Listen-Host hat 2, das
  Protokoll war aus. `tools/patch_dustgame_pkg.py` ändert in `DUSTGAME.XXX` den `ByteConst` (Datei-Offset 0x30d4e1)
  auf 2, Original als `DUSTGAME.XXX.orig`. Der Hook leert jetzt alle Kategorien (sonst wächst z. B. `CharacterPosition`).
  Host um 10:50 damit neu gestartet. **Hack-Test 12:35 bestanden:** Eintrag `hack: {'ismissionobjective': 1, 'teamid': 1, …}`,
  `objectives held by team 0/1: 0/1`, danach alle 10 s `DamageMcc 0 10000` (teamID passt also). Der erste Host-Start davor
  hing im bekannten Starthänger (RSX queue stuck), der zweite lief. **Fehler:** `actorid` im Hack-Eintrag ist der hackende
  Charakter, nicht das Ziel, alle Hacks zählten als ein Ziel. Jetzt nach Hack-Position (Radius 3000), Test 13:00:
  `objectives held by team 0/1: 4/0`, `DamageMcc 1 40000`. Die Salve kommt real alle ~12,3 s (Poll-Schleife), das MCC
  fällt also nach ~12 min statt 9,5. **Ganzer Ablauf bestanden (13:10):** MCC zerstört, Match sauber beendet, 462 WP →
  +962 SP, +123 100 ISK, Fahrzeugverlust gebucht (`vehicle lost for 2100001617: {353808: 1}`, Server: `lost {353808: 1}`),
  Host-Neustart 60 s danach automatisch, neuer Host um 13:12 bereit. Kein Treffer-Feedback (`DamageMcc` wirkt direkt auf
  den VIC); Nutzerwunsch: Geschützschuss (`DustAntiMccMissile`) statt direktem Schaden. Achtung: Ein Client mit `-autologinserver` meldet sich ohne
  PSN-Ticket an und bekommt den gemeinsamen Offline-Benutzer (ohne eigene Fahrzeug-Fittings); eigene Charaktere nur
  mit RPCN-Anmeldung.
- **Fahrzeuge werden nicht abgerechnet (2026-11-01, Nutzer):** Log: `CheckOutFittingForPendingDeployVehicle` kommt,
  `DestroyFitting` für Fahrzeuge nie. Script: `DustVIC.DestroyFitting`/`CheckinFitting` tun nur etwas, wenn
  `mFittingOwner` ≠ -1; den setzt die RDV-Auslieferung, die Patch 0.2 ersetzt. Bei Fahrzeugen ruft auch kein Script
  `OwnerDied` (nur Pawn, Installation, MCC). Fix im Dev-Hook: Fahrzeug-Checkouts merken, bei Matchende bzw. Abgang
  gelten noch ausgecheckte als verloren (auch überlebende). Sauberer wäre, im RDV-Patch `mFittingOwner` zu setzen.
  Automatischer Host-Neustart nach Matchende: `DUST_RESTART_AFTER_MATCH` (Standard 60 s) im CREST-Server.

- **Neues Loch in der Karte (2026-11-01):** Tester ist auf dem Vulkan-Client (Host Null) durchgefallen, laut Deploy-Karte
  in der Nähe der Straßenkurve südwestlich eines Versorgungsdepots, bei einem Tor mit Silos. Position beim Sturz nicht gesichert.
  Offen: Fällt man auf dem Client auch ohne Host-Korrektur durch (Client-Loch), oder fällt nur der Host-Pawn und zieht den Client mit
  (Host-Kollision, Thema Patch 0.5)? Gleiche Stelle wie (153509, 41800)? Nachstellen, dicht davor stehen bleiben, dann
  `live_dump.py` beider Instanzen und `pawn_state.py`.
  Abbild davor (`…_20261101_083609_live` Client, `…_083612_live` Host): beide `PHYS_Walking` bei (19823.5, -13418, 45091.9)
  auf einer `StaticMeshCollectionActor` (Gebäude) in MN_CRATERS01, Host und Client also einig. Andere Stelle als (153509, 41800).
  Bild: Die Geländekante ist grob gezackt und hat zwischen den Zacken einen Spalt zur Gebäudewand. Das sieht nach einer
  Loch-Maske in grober LOD aus. Weil man ganz durchfällt statt zurückgezogen zu werden, fehlt die Kollision im Spalt mindestens
  auf dem Host. Ob das Original den Spalt auch hatte, ist unklar.
  **Gezielter Sturz (Abbilder `…_083855` Client, `…_083858` Host, `…_083901` Client, `…_083904` Host):** Beide Seiten sind
  durchgehend `Falling` auf derselben Bahn: Höhe 23807 → 13505 → 4076 → -6114, Spalt bei etwa (20900, -15340). Die Kollision
  fehlt also im Client genauso wie im Host. Der Client nutzt für den eigenen Pawn die unveränderte Kollision des Spiels, also
  liegt das Loch sehr wahrscheinlich in den Kartendaten oder kommt von RPCS3, nicht von Patch 0.5. Der Host richtet es nicht an.
  **Korrektur, Ursache gefunden (Abbilder `…_090329`–`…_090338`):** Tester stand bei (22158, -12585) still und hüpfte auf und ab,
  der Client wechselte zwischen `Falling` und `Walking` auf `MegaTerrain_0`. Gelände-Kollisionskacheln
  (`scratchpad`-Skripte `tiles_at.py`/`fine_tiles.py`/`pawn_list.py`): Unter dem Spieler hat der Client Kacheln bis 2048,
  der Host nur ab 16384. Die feinen Kacheln des Hosts (2048/4096) liegen seit über 30 Minuten unverändert bei
  x 23040..39424, y 6144..26624. Dort steht `DustConsole_0` (32367, 16829), der **letzte** Eintrag der PawnList. Die PawnList
  des Hosts hat in Skirmish 54 Einträge (Geschütze, Fahrzeuge, Versorgungsdepots, CRUs, Konsolen, MCCs), der Spieler steht an
  5. Stelle. Höhle 3 (`0x7fb7bc`) ruft `FUN_008240e8` für jeden Eintrag auf, und offenbar gewinnt der letzte Aufruf (keine
  Vereinigung). In Test 6 war die Liste kürzer. Der Host fällt also auf grober Kollision mit großem Loch unter dem Gebäude durch
  und zieht den Client mit, das ist kein Kartenfehler. Fahrzeuge betrifft es nicht (eigene Kollision über RigidBody).
  **Patch 0.6 (2026-11-01):** Höhle 3 ruft nur noch Pawns mit `DustPlayerController` (vtable 0x197b698) auf, 40 Plätze.
  Host-Sicherung `NPUB30643_patch.yml.before_lod06`. Der erste Host-Start danach hing schon beim Booten (RSX queue stuck nach
  39 s, keine einzige CREST-Anfrage, Patch laut Log angewandt), der zweite lief normal. Das ist also der bekannte Starthänger.
  Test mit 2 Fake-Clients (`--play`, je ein Team, Abbild `…_093040_live`, `player_tiles.py`): Spieler bei (21630, 2420)
  bekommt Kacheln bis 2048, Spieler bei (21586, -11856) nur 8192. **Es bekommt also nur ein Spieler feine Kollision.**
  Grund: `FUN_008240e8` geht über das Wurzelraster (`comp+0x24c` × `+0x250`) und ruft `FUN_00823078` mit einem Parameterblock
  auf, der Typ steht darin bei +0x3c. `FUN_00823078` setzt bei Typ-Bit 1 Knoten+0x94 zurück, bei Bit 2 Knoten+0xa4. Das
  sind genau zwei Plätze pro Knoten (im Original Kamera und eigener Pawn, Typ 3 = beide). Mehr als zwei Punkte gehen so nicht.
  Optionen: (a) zwei Spieler über Typ 1 und Typ 2 (billig, aber nur 2); (b) den Rechteck-Test in `FUN_00823078`
  (Rechteck um den Punkt in Rasterkoordinaten, `FUN_008240e8` +0xf8..+0x104, Umrechnung `FUN_00823dd8`) durch „nah an
  irgendeinem Spieler“ ersetzen, analog zu den Höhlen 1 und 2. Das ist die eigentliche Lösung für 32 Spieler.
  Gegenprobe 09:32 (Abbild `…_093211_live`): Tester auf dem Vulkan-Client bei (21599, -11866) hatte auf dem Host Kacheln von
  16384, ein Fake-Client bei (30564, 17360) Kacheln von 2048. Kurz danach fiel der Tester an dieser Stelle durch.
  **Patch 0.7 (2026-11-01), Vereinigung über alle Spieler:** `FUN_00823078` geht für Knoten fern vom Punkt in den
  Löschpfad ab `0x823164`: Er löscht die Markierung des Platzes und steigt rekursiv in die Kinder ab. Deshalb gewann
  der letzte Aufruf. Höhle 3 ruft jetzt den ersten Spieler-Pawn mit Typ 3 auf, alle weiteren mit 0x103. Höhle 4 an
  `0x823164` springt bei Bit 0x100 in den Epilog `0x8236c8` (`jump`-Eintrag im calloc-Block). Der Typ läuft unverändert
  durch die Rekursion und wird sonst nur auf Bit 1 und 2 geprüft. Host-Sicherung `NPUB30643_patch.yml.before_lod07`.
  Nach jeder Patch-Änderung übersetzt RPCS3 neue PPU-Objekte, das Fenster kommt dann erst nach über 60 s.
  `restart_host.ps1` meldet deshalb „No RPCS3 window“, obwohl der Host weiterläuft.
  Test (Abbilder 09:39–09:42, 2 Spieler: Fake-Client und Tester): Beide haben in allen 7 Abbildern Kacheln von 2048,
  zuletzt bei (53326, -10471) (in einem LAV, `NceVehicleWheeled_0`) und (27821, -18560), also etwa 27 000 Einheiten
  auseinander. Kacheln 211 → 316. Host-FPS im Fenstertitel 27–34 während der Abbilder (vorher 46 ohne Spieler),
  nicht sauber gemessen. Offen: Kosten pro Spieler bei 16/32 Spielern (Tick, Kachelzahl, Speicher).
- Gibt es Grenzen im NetDriver oder in `sys_net`/RPCS3? Bis 5 Spieler keine.
- Wie skaliert der Game-Thread (~11 ms/Tick bei 5 Spielern) mit aktiven Spielern und mit mehr als 5? Wie hält man den Host
  ohne VSync auf einem festen Takt (z. B. 30 oder 60), damit er nicht unnötig CPU verbrennt?
- Wie teuer sind aktive Spieler (Laufen, Schießen) im Vergleich zu untätigen Pawns?
- Ab wie vielen Clients lohnt ein zweiter PC, damit die CPU-Konkurrenz die Messung nicht verfälscht?
- Wie lassen sich headless Clients mit Eingabe-Wiedergabe betreiben (Pad-Eingaben in RPCS3 skripten)?
- **Kick im Gefecht durch Info-Bildschirm (2026-10-30, Client b, Skirmish):** Kein Kick vom Host. Client b öffnete
  einen Spieler-Info-Bildschirm (`showInfoScreen._GetCharacterInfo` → `otherCharactersClient.GetCharacterInfo`) mit der
  Gefechts-URI `GET /battlecharacters/2100001612/`; unser 404 war im Client unbehandelt → `UNCAUGHT_TOP_LEVEL_EXCEPTION`,
  Netz getrennt, Host meldet `OnBattleMemberLeftFromUnreal`. Fix: Route `/battlecharacters/{id}/` liefert das
  Charakter-Dokument des eigenen Charakters hinter der Gefechts-ID, sonst CCPs Offline-Charakter mit dem Mitgliedsnamen.
  Im Prozess geprüft, in RPCS3 offen (Server-Neustart nötig).
- **Fahrzeuge im Gefecht: „No Assets Available“ (2026-10-30, Nutzer, eigenes Fahrzeug-Fitting, Ambush):** Kommt aus
  `ui/quickFitting._OpenVehicleFittingSubPage`, wenn die UE3-Prüfung `unrealFittingSvc.AllowSpwanVehicleInFitting()` nicht
  `mVehicle_Spawn_OK` liefert. Die Fittings selbst werden dort gar nicht gelesen. Vermutung: Ambush erlaubt keine Fahrzeuge.
  Nächster Test in Skirmish/Domination; erst wenn dort die Kategorien kommen, die Fitting-Liste prüfen.
  **Skirmish (2026-10-30, Client b, LAV-Fitting `353808:351320,351320,352314`):** Menü und Fitting-Liste gehen, Anfordern
  endet mit „Vehicle request denied – Location inaccessible“. Host-Log: `DeployVehicleWithFitting` kommt an,
  `CheckOutFittingForPendingDeployVehicle` checkt aus (kein Kick), direkt danach `ClearPendingVehicleFittingForChar(id, True)`
  und Rückgabe ins Inventar. Die Ablehnung fällt also in UE3 bei der Landeplatzsuche fürs RDV, nicht in Python/Fitting.
  Hypothesen: Platzsuche (Trace nach oben/unten) scheitert auf dem Host, weil dort Kollision oder Landezonen fern vom
  Host-Pawn fehlen (vgl. LOD-Kollision, Patch 0.5), oder Ort ungeeignet (Deckung, Hang). Nächste Tests: auf freier, ebener
  Fläche anfordern, einmal nahe am Host-Spawn; in Ghidra/UPK den String bzw. `DeployPendingVehicle` suchen.
  **Nachtrag:** Auch auf offenem Gelände abgelehnt (Nutzer). UnrealScript (`DUSTGAME.XXX`, `uscript.py`):
  `DustPlayerController.DeployPendingVehicle` checkt das Fitting aus und ruft die **native**
  `DustControllerSharedComponent.HandleRDVRequest(charID, typeID, module, Location des Controllers)`; Ergebnis ≠ 0
  (`ERDVRequestResult`, hier `RDVR_Denied_InvalidLocation`) → Rückgabe. Das RDV ist ein KI-geflogenes Dropship
  (`DustAIBehaviour_RDV`, `DustAIMgr.m_pRDVWorld`, `m_mRDVSectionsNavData`, `m_pRDVStreamingManager`,
  `m_aRDVLocationPoints`). Hypothese: Die RDV-Navigation der KI fehlt auf dem Listen-Host (nicht geladen oder wie die
  KI-Spawns im Release herausgenommen), dann scheitert jeder Ort. Nächster Schritt: native `HandleRDVRequest` in Ghidra
  (welche Prüfung liefert InvalidLocation). Testhilfe: Dev-Controller hat `RDV <typeName> <fitting> X Y Z` (ruft
  `HandleRDVRequest(-1, …)` an beliebiger Stelle), `ShowRDVDropOff 1`, `SetDebugRDVPoints`.
  **Ghidra (2026-10-31):** `execHandleRDVRequest` 0x14f3410 ruft vtable-Slot 0x3fc (vtable 0x1959ac8 aus dem
  InternalConstructor 0x14e4ea8) = `FUN_006ea594`. Dort: Ergebnis 1 (NotAllowed) ohne RDV-Dienst, 2 im
  Versorgungsdepot-Zweig ohne freien `GetRDVLocationPoint`, sonst `FUN_007cc670` (UDustSvcRDV). Die erste Prüfung dort,
  `bl 0x0e4cb0` bei 0x7cc6ec, ist im Release ein Stub `li r3,2; blr` → **immer `RDVR_Denied_InvalidLocation`**, egal wo.
  Danach echter Code (Abstand zu anderen RDVs `FUN_007cb9b8`, Warteschlange `FUN_007cc4a8`, Benachrichtigungen).
  Patch 0.1 `rpcs3_patches/host_rdv_request.yml` (Aufrufstelle → `li r3,0`, Stub selbst nicht anfassen, vermutlich
  zusammengelegt) im Windows-Host eingetragen (Sicherungen `*.before_rdv`), **ungetestet**. Offen: ob die Warteschlange
  abgearbeitet wird und das KI-Dropship fliegt (KI-Teile könnten ebenfalls fehlen); Quoten entfallen mit dem Stub.
  **Test 0.1 (2026-10-31):** „… has been queued“, aber kein Dropship; zweite Anforderung `requestNotFinish` („pending
  vehicle“), weil Python das Fitting bis zur Auslieferung als pending hält. Ghidra: Die Abarbeitung `FUN_007cbb90`
  (UDustSvcRDV-vtable 0x1984c18, Slot 0x154) entfernt fällige Einträge nur noch, der Auslieferungs-Aufruf fehlt;
  `NceVehicleRDV.DebugDropVehicle` ist ein leerer Stub. Vollständig vorhanden: `ADustSpawner::SpawnAndFitVehicle`
  (`FUN_007b61a4`, r4 typeID, r5 Fitting, r6/r7 Ort, r8/r9 Rotation, r10 Team) und `SpawnByTypeImpl` (`FUN_0079f21c`).
  **Patch 0.2:** Code-Höhle auf 0x7cbcc4 spawnt das Fahrzeug aus dem Eintrag (+500 in X und Z, kein Dropship),
  `dustdevhook` löscht das pending-Fitting nach angenommener Anforderung (Checkout läuft synchron davor). Im Host
  geladen. **Test 0.2 (2026-10-31, Client b, Skirmish): LAV wird gespawnt und funktioniert.** Die Abarbeitung läuft
  also (Verzögerung > 0). **Panzer und Dropships spawnen auch, aber auf dem Anforderer (Tod).** Patch 0.3: +1024 in
  X und Y, +768 in Z (~14,5 m neben dem Anforderer). **Test 0.3 (Nutzer, bis 2026-11-01): Panzer und Dropships spawnen
  neben dem Anforderer und funktionieren.** Echter Dropship-Anflug: `DustAIBehaviour_RDV` (vtable 0x19b3a40, Konstruktor
  0x15e7fe8, Objekt 0xe0 Bytes) hat im Release nur die 84 UObject-Slots, die ganze Flug-KI fehlt. `NceVehicleRDV` als
  Fahrzeug ist da (`OnDropVehicle` 0x882a64 spielt nur Effekte ab, `CreateDropOffMarker` 0x882bb4). Ein Anflug ginge
  nur mit eigener Steuerung (RDV spawnen, Fahrzeug anhängen, Position pro Tick setzen, abwerfen, wegfliegen).
  Offen: Ort in engem Gelände (der Versatz kann in Wände fallen), fehlende
  Quoten, Docker-Host (Patch fehlt in dessen Datenvolume), Client-SDATs ohne neuen dustdevhook.
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
