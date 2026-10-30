# Projekt: Dust 514 wiederbeleben (CREST-Server plus Gefechts-Host)

## Kontext

Hobby-/Preservation-Projekt. Dust 514 (PS3, UE3, im Mai 2016 abgeschaltet) wird mit einem privaten Open-Source-CREST-Server
wieder spielbar gemacht. Der Nutzer besitzt Spiel und Lizenzdatei (.rap) auf seiner eigenen PS3 und arbeitet ausschließlich mit
eigenen Dateien. Es werden keine Spieldaten, Firmware oder Schlüssel weitergegeben. CCP hat nie ein Server-Binary veröffentlicht,
daher dient der Listen-Server-Pfad des Retail-Clients (RPCS3) als Gefechtsserver. Die Arbeit besteht aus Analyse der eigenen Binary
(Ghidra, Speicherabbilder) und RPCS3-Patches mit dem Ziel der Interoperabilität mit dem privaten Server.

## Arbeitsregeln

- **Token sparen:** Diese Datei ist kurz gehalten. Der Stand der Gefechts-Arbeit steht in `docs/battle_feasibility.md` (Kompaktfassung).
  Die lange Fassung `docs/archive/battle_feasibility_full.md` nur gezielt per Suche öffnen, nicht komplett lesen.
- **Notizen:** Neue Funde, Hypothesen und gescheiterte Versuche laufend in `NOTES.md` festhalten (Abschnitte Funde, Hypothesen,
  Ausprobiert, Offene Fragen). Zu Beginn jeder Session `NOTES.md` lesen. Bestätigte Ergebnisse später in
  `docs/battle_feasibility.md` übernehmen und dort kurz halten (Ergebnis statt Chronik).
- **Git:** Jeden sinnvollen Zwischenstand committen, besonders Patches (`rpcs3_patches/`) und Server-Code.
- **Originale schützen:** Nur mit Kopien der Dumps arbeiten. Vor Änderungen an RPCS3-Configs und Patch-Dateien Sicherungen
  (`*.before_*`) anlegen.
- **Nichts Geschütztes committen:** Binaries (EBOOT, PRX, ELF), Dumps, `.rap`, Schlüssel, Firmware und Speicherabbilder gehören nie ins
  Repo (`research/` bleibt außerhalb). Die `.gitignore` pflegen.
- **Messen statt vermuten:** Performance- und Skalierungsaussagen immer mit Messwerten belegen (FPS, Tick, RAM, CPU pro Thread).
- **Klein anfangen:** Eine Änderung pro Test, danach Ergebnis festhalten.

## Stand (Kurzfassung, Details in `docs/battle_feasibility.md`)

- CCPs Gefechtsserver war derselbe UE3-Code als Windows-Dedicated-Server (nicht verfügbar). Der PS3-Client hat einen Offline-Modus
  mit allen Gefechtsdiensten im Client. Ein Dedicated-Pfad im PS3-Binary ist unwahrscheinlich.
- **Entscheidung:** Listen-Server auf RPCS3 mit gezielten RPCS3-Patches. Ein Server-Nachbau wäre ein Mannjahre-Projekt.
- **Läuft:** Host + bis zu 4 Clients (RPCS3-Instanzen auf einem PC), Ambush, Skirmish, Domination. Beitritt über die Gefechtssuche, Credentials über den
  CREST-Server. Host ohne GPU im Docker (Null-Renderer mit RPCS3-Fix). Kollision fern vom Host gelöst (Patch 0.5, drei Code-Höhlen,
  `rpcs3_patches/host_full_outpost_lod.yml`).
- **Gemessen:** Host (Null-Renderer, Weltrendering per Patch aus, `-novsync`) 84 Ticks/s, ~12 ms pro Tick, 2,4 GB RAM bei 5 Spielern.
  Vorher 23 Ticks/s. Engpass jetzt der Game-Thread. Engine-Tickrate ist auf 30 konfiguriert. Mehr als 5 Spieler nicht getestet.
- **Keine Bots:** KI-Spawn-Logik ist im Release-Build herauskompiliert. Gegner gibt es nur über echte Spieler.
- Ziel laut Nutzer: 32 Spieler (in der Beta war 32 das Limit, 48 geplant).

## Kontext zum Original (aus öffentlichen Quellen)

- CCP-Dev-Blog „Scaling the Universe of DUST 514" (Lin Luo, 2011): Pro Match ein Battle-Server-Prozess, vom EVE-Backend gestartet und
  parametrisiert, nach dem Match beendet, viele Instanzen pro Multi-Core-Maschine. Das war sehr wahrscheinlich ein nativer x86-Build und
  ist daher kein Maßstab für die Last im Emulator.
- Warroom: war laut Handbuch die Pre-Battle-Lobby pro Match und Team (später ein Mercenary Dropship). Die Karte `WB_WARROOM_CA` liegt in den
  PSARCs. Mercenary Quarters waren der persönliche Bereich zwischen den Matches. Ob der Warroom als Vorphase des Gefechts nutzbar ist,
  ist offen.
- Spielmodi im Endstand: Ambush, Ambush OMS, Skirmish, Domination, Academy (Einsteiger); Acquisition laut Wikipedia unklar.

## Nächste Schritte

1. **Harte Grenzen prüfen (vor dem Messen, Ghidra):** Spielerobergrenze im Binary (MaxPlayers/MaxClients im NetDriver, Größe der
   Verbindungs-Arrays), Socket-Limits in `sys_net` bzw. RPCS3, Speicherbedarf pro Verbindung (Channels, Replikationsstate) im
   emulierten 256-MB-Hauptspeicher. Ist 16 fest einkompiliert, zuerst das lösen.
2. **Test-Harness für Schritt 3:** Ohne Bots gibt es keine 31 Mitspieler. Nötig sind headless Clients im Docker (Null-Renderer wie beim Host),
   eine Eingabe-Wiedergabe (Laufen, Schießen; untätige Clients unterschätzen die Replikationslast), eine verlässliche Tick-Messung am
   Host (FPS ≠ Server-Tick) und ein automatisierter Host-Start pro Messlauf (aus Schritt 6 vorgezogen).
3. **Skalierung messen:** 2 → 4 → 8 → 16 → 32 Clients (FPS, Tick, RAM, CPU je Thread, Netzlast). Dafür echte Clients oder mehrere Instanzen.
4. **Fallstelle prüfen** (153509, 41800) und Kollision mit mehr als 2 Spielern bestätigen. Offene Funktionen: `FUN_007f9b54`, `FUN_007f7b0c`.
5. **Matchende und Belohnungen** im CREST-Server (`POST battle.completed`, `member.completed`), Rückkehr in die Merc Quarters.
6. **Docker-Dauerbetrieb:** Watchdog, Neustart des Hosts pro Match (ein Moduswechsel im laufenden Host stürzt ab), Instanzen pro Maschine.
7. Offene Modi: Acquisition (Startposition), Ambush OMS (ungetestet).
8. Warroom-Karte testweise als Vorphase laden.
9. **Erst nach Schritt 3 entscheiden:** Reicht RPCS3 für 32 Spieler? Falls nicht, ist ein statischer Recompiler (ps3recomp,
   github.com/sp00nznet/ps3recomp) eine mögliche Option, um die Tickrate zu verbessern. Er ist aber ein großer Aufwand: Alle bisherigen
   Referenzprojekte sind kleine Singleplayer-Spiele, und der Host braucht auch die SPU-Jobs. Bisher ist er nicht begonnen.
