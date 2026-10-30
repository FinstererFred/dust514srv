# Notizen

## Funde

## Hypothesen

- Die Spielerzahl könnte unabhängig von der Performance hart begrenzt sein: MaxPlayers/MaxClients im NetDriver, feste
  Verbindungs-Arrays, Socket-Limits in `sys_net`/RPCS3. Retail lief mit 16 gegen 16. Ob der Listen-Server-Pfad dieselbe Grenze hat,
  ist unbekannt.
- Der Speicher pro Verbindung (Channels, Replikationsstate) könnte im emulierten 256-MB-Hauptspeicher knapp werden, auch wenn ein Client
  32 Pawns problemlos hält. Die 4,6 GB Host-RAM sagen darüber nichts.
- Untätige Test-Clients unterschätzen die Last am Host deutlich. Für aussagekräftige Messungen braucht es Bewegung und Schüsse.
- Die 26 FPS bei 2 Spielern sind vermutlich größtenteils Fixkosten (Welt, Physik, SPU-Jobs). Aussagekräftig sind die Kosten pro
  zusätzlichem Spieler.

## Ausprobiert

## Offene Fragen

- Wo liegt die Spielerobergrenze im Binary, und wie groß ist sie? (Ghidra: Strings wie `MaxPlayers`, `MaxClients`, NetDriver-Init)
- Wie lässt sich der Server-Tick am Host zuverlässig messen, getrennt von der FPS?
- Wie lassen sich headless Clients mit Eingabe-Wiedergabe betreiben (Pad-Eingaben in RPCS3 skripten)?
