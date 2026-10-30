# Gefechte (Battles) für den wiederbelebten DUST-514-Client – Machbarkeitsstudie

Stand 2026-10-23, Client 03.19 (Build 2.13.0.249 `DUST-ALPHA`). Grundlage: dekompilierter Python-Code
unter `research\decompiled_0319\COMMON` (Pfade unten relativ dazu, Zeilennummern beziehen sich auf den
dekompilierten Code), die Spieldatenbank `VAULT\CATMADB.PICKLE`, die Archive in `DUSTGAME\COOKEDPS3_ARC`
und die entpackten Coalesced-INIs aus `ProtoDroidBot/514_CROP-DUSTInG`. Die EBOOT (UE3-C++-Teil) ist noch
nicht ausgewertet. Was nur dort entschieden wird, ist unten als **offen** markiert.

## Kurzfassung

1. Der Ablauf im Client ist vollständig in Python und gut lesbar. Ein Gefecht beginnt damit, dass der
   Server dem Client über den Notification-Stream `OnBattleMemberConnect` mit Adresse, Port und
   `credential` schickt. Der Client führt dann den UE3-Konsolenbefehl
   `CleanLoad <adresse>:<port>?credential=…?Team=…` aus. Alle nötigen CREST-Formate stehen im Code.
2. Der Gefechtsserver bei CCP war **derselbe UE3-Code mit demselben Python**, nur als Dedicated Server
   (`GIsServer and not GIsClient`) und, nach der Cook-INI zu urteilen, als **Windows-Build**. Dieses
   Binary ist nicht veröffentlicht.
3. **Wichtigster Fund:** Der PS3-Client enthält einen Offline-Modus, der die **kompletten
   Gefechtsserver-Dienste im Client selbst startet** (`userClient._InitBattleServices` →
   `startmini.GetBattleServices`) und Fake-Inventar für 100 Offline-Charaktere anlegt. CCP hat also
   Client und Gefechtsserver in einem Prozess laufen lassen. Alle Karten liegen lokal vor.
4. **Empfehlung:** Weg (d), dann (b). Zuerst ein lokales Gefecht im Client (Standalone), danach der
   Client als Host (Listen-Server) für weitere Spieler. Ein Nachbau des Gefechtsservers (c) kommt nicht
   in Frage.
5. **Nächstes Experiment** (nur serverseitig, ohne Client-Patch): Der CREST-Server bietet ein Fake-Gefecht
   an. Beim Beitritt schickt er `OnBattleMemberJoined` und dann `OnBattleMemberConnect`, wobei als
   „Serveradresse“ ein **lokaler Kartenname** eingesetzt wird. Damit testen wir die ganze Kette bis
   `CleanLoad` und sehen, ob die PS3-Engine die Karte lokal lädt (Details in Abschnitt 5).
6. **Stand 2026-10-24 (Experiment 9):** Mehrspieler funktioniert grundsätzlich. Ein Client hostet die Ambush-Karte
   per `?listen`, ein zweiter (zweite RPCS3-Instanz mit lokalem RPCN-Server) tritt mit einer Credential bei, die der
   Host per Dev-Befehl registriert hat. Danach spawnt er im gegnerischen Team.
7. **Stand 2026-10-25:** Jeder Spieler hat eine eigene Gefechts-ID (`?battleID=` schaltet `DustTeamGame.Login` auf
   den Credential-Zweig). Clients treten über die Gefechtssuche bei, Credentials vergibt der CREST-Server. Host und
   Client starten ohne Tastendruck (`-autologinserver`, `-autologincharindex`, `-autologinbattle`). Ambush,
   Skirmish und Domination laufen mit zwei Spielern; Acquisition lädt, hat aber noch falsche Startpositionen.

---

## 1. Ablauf im Client: vom Menü bis zur Verbindung

### 1.1 Beteiligte Dienste

| Dienst | Datei | Aufgabe |
|---|---|---|
| `uiSvcBattle` | `dust/ui/services/uiSvcBattle.py` | Gefechtssuche (Flash-Seite `battleFinder2`), Auswahl, Abbruch |
| `battleClient3` | `dust/battleClient3.py` | CREST-Abfragen (Theater, Warteschlangen, Gefechte), Beitritt, Backend-Benachrichtigungen |
| `pingClient` | `dust/pingClient.py` | Regionen und Ping (`/battleserver/regions/`) |
| `dustClient` | `dust/dustClient.py` | verarbeitet „Server bereit“, lädt Battle/District/System, Ergebnisse am Gefechtsende |
| `dustUnreal` | `dust/dustUnreal.py` | setzt den UE3-Befehl `CleanLoad …` ab |
| `spawnClient` | `dust/spawnClient.py` | schickt die gewählte Ausrüstung im Gefecht per UE3-RPC an den Server |
| `squadClient` | `dust/squadClient.py` | Trupps (`squads`), für ein Solo-Gefecht nicht nötig |

### 1.2 Schritt für Schritt

1. **Gefechtssuche öffnen.** `uiSvcBattle.OnOpenedBattleFinderNotification` ruft
   `battleClient3.SetPolling(True)` auf. `BattleClient3.Reload` (Z. 78) fragt dann alle 15 s ab:
   - `GET rootData['battleTheatres']` (`vnd.ccp.eve.BattleTheatreCollection-v1`)
   - `GET rootData['battleQueues']` (`vnd.ccp.eve.BattleQueueCollection-v1`)
   - `GET rootData['battles']` (`vnd.ccp.eve.BattleCollection-v1`)
   - `conflictClient.GetMyCorporationConflicts()`

   Diese Anfragen kommen bei uns schon an: `/battles/theatres/`, `/battles/queues/`, `/battles/`,
   `/battleserver/regions/` werden laut `requests.jsonl` von CCPs Offline-Handlern mit `{"items": []}`
   beantwortet (`offline/offlineResourceMisc.py`, `OfflineBattles` Z. 180). Darum ist die Liste leer.
2. **Auswahl** (`UISvcBattle.OnSelect`, Z. 78). Es gibt zwei Wege:
   - **Theater mit Warteschlange** (`'queue' in theatre`): `BattleClient3.JoinQueue` (Z. 231) schickt
     `POST queue['href']` mit Inhaltstyp und Accept `vnd.ccp.eve.BattleQueueTicket-v2` und dem Body
     `{"regions": [{"name", "latency"}], "options": [{"href"}], "character": {"href"}}`. Die Antwort
     wird als `queueMember` gespeichert (der Client erwartet `href`, `queue.href`, `waiting`,
     `estimated`). Das Matchmaking läuft komplett im Backend.
   - **Gefecht aus der Liste** (Theater `public`/`corporation`): `UISvcBattle.JoinBattle` (Z. 128)
     verlangt `battle['status'] >= 3` und zeigt bei `teamSelect` eine Seitenwahl an. Danach schickt
     `BattleClient3.JoinBattle` (Z. 301) `POST battle['members']['href']` mit
     `vnd.ccp.eve.BattleMemberCreate-v1` und `{"character": {"href"}, "team"?, "region"?}`. Die
     Antwort hat den Typ `vnd.ccp.eve.BattleMember-v1`. Bei `403 AlreadyInBattleForbiddenError` löscht
     der Client die alte Mitgliedschaft (`headers['location']`) und versucht es erneut.
3. **Backend meldet die Mitgliedschaft:** `OnBattleMemberJoinedFromBackend` (Z. 328) übernimmt die
   Nachricht nur, wenn `notification['character']['href']` der eigene Charakter ist. Danach holt
   `UpdateBattle` (Z. 356) `GET battleMember['battle']['href']` (`vnd.ccp.eve.Battle-v1`). Die UI
   zeigt „Beitritt“ und navigiert auf der Sternkarte über `region/constellation/system/planet/district`.
4. **Backend meldet „Server bereit“:** `OnBattleMemberConnectFromBackend` (Z. 344) wartet höchstens
   3 s (`CONNECT_DELAY`) und leitet die Nachricht lokal weiter, wenn ein `battleMember` existiert.
   `DustClient.OnBattleMemberConnectNotification` (Z. 244) macht dann Folgendes:
   - `serverInfo = '%s:%s' % (notification['server']['address'], notification['server']['port'])`
   - liest `credential`, `team` (`attacker` → 0, `defender` → 1), `battle.id`, `battle.href`, `href`
   - lädt `GET battle` (`Battle-v1`), optional `district` (`District-v1`) und `system` (`System-v1`)
   - sendet `OnProceedBattleConnectNotification`
5. **Verbindung:** `DustUnreal.OnProceedBattleConnectNotification` (Z. 69) baut den Befehl
   `CleanLoad {serverInfo}?credential={credential}?Team={teamID}?LightingMode={lightingMode}?DefaultArmor={armor}`.
   Nach `FadeOut` und 1 s Pause setzt der Client seinen Ort auf „im Gefecht“ und führt den Befehl über
   `GetUnrealService('Util').ExecConsoleCommand` aus. `CleanLoad` ist ein Dust-eigenes UE3-Kommando.
   Was es genau tut, steht in der EBOOT (**offen**). Vermutlich ist es ein `ClientTravel` auf eine
   UE3-URL mit Standardport 7777 (`[URL] Port=7777`, `NetworkDevice=IpDrv.TcpNetDriver` in
   `PS3-DustEngine.ini`).
6. **Im Gefecht:** Ausrüstung und Fahrzeuge schickt der Client per
   `dustClient.InvokeSvcMethodOnBattleServerAsync` → `_pyunreal.GetRootObject().InvokeSvcMethodOnBattleServer(...)`
   über UE3-Replikation an den Python-`battleServer` (`SpawnCharacterWithFitting`,
   `DeployVehicleWithFitting`, `ChangeCharacterFittingDuringBattle`). Ergebnisse kommen auf dem
   umgekehrten Weg zurück (`dustClient.OnEndOfMatchResults`, `…PartialLootReward`, Zugriffsrolle
   `ROLE_BATTLE_SERVER`).

Daneben gibt es einen Entwickler-Weg: Beim Wechsel in die Söldnerunterkunft tritt `-autologinbattle=<name>`
in `sys.argv` automatisch einem Gefecht bei (`battleClient3.OnQuitToMercQuartersNotification`, Z. 373).
Auf der PS3 lassen sich Kommandozeilenargumente aber kaum setzen.

### 1.3 Notification-Stream

`characterConnectionClient._NotificationCallback` (Z. 144) und `userBase._NotificationCallback` lesen
jede `data`-Zeile des Streams so:

```
name = data['contentType'].split('.')[-1]   # "OnBattleMemberConnect-v1"
name = name.split('-')[0]                    # "OnBattleMemberConnect"
notificationShared.SendBackendNotification(name, data['body'])   # → OnBattleMemberConnectFromBackend
```

Eine Stream-Zeile sieht also z. B. so aus:
`{"sn": 7, "data": {"contentType": "application/vnd.ccp.eve.OnBattleMemberConnect-v1", "body": {...}}}`.
Der Body kommt eins zu eins beim Listener an.

Diese Benachrichtigungen erwartet der Client für Gefechte (`battleClient3.StartProcess`, `dustClient.StartProcess`):

| Name | Nutzen | benötigte Body-Felder (laut Code) |
|---|---|---|
| `OnBattleQueueJoined` | Warteschlangen-Ticket | wie BattleQueueTicket (`href`, `queue.href`, `waiting`, `estimated`, optional `message`) |
| `OnBattleQueueLeft` | Ticket weg | `href`, optional `message` |
| `OnBattleMemberJoined` | Spieler ist Gefechtsmitglied | `href`, `character.href`, `battle.href` |
| `OnBattleMemberLeft` | Mitgliedschaft beendet | `href` |
| `OnBattleMemberConnect` | Server bereit, verbinden | `href`, `server.address`, `server.port`, `credential`, `team`, `battle.id`, `battle.href` |
| `OnBattleMemberDisconnect` | nur lokal weitergereicht | – |
| `OnBattleTerminated`, `OnClusterShutdownInitiated/Cancelled` | Abbruch/Meldungen | `message` (Cluster) |

### 1.4 Battle-Objekt (`vnd.ccp.eve.Battle-v1`)

Diese Felder werden gelesen (`uiSvcBattle._FormatTheatreBattles`, `_GetNavigationNodes`, `_FormatBattle`,
`dustClient`): `href`, `id`, `name`, `status` (ab 3 beitretbar), `teamSelect`, `startDate`,
`attacker.name/href`, `defender.name/href`, `region.id`, `constellation.id`, `system.id/href`,
`planet.id/name`, `mode.id` (für `dustClient.GetBattleModeID`, UnrealCallable), `members.href`,
optional `district`, `serverRegion`, `maxPlayers`, `totalPlayers`, `queue`, `conflict`.
`BattleOptionalKeys` füllt fehlende Schlüssel mit `None`, die Namen sind im dekompilierten Code aber nur
als Zahlen zu sehen. Theater brauchen `key` (`public`/`corporation`/`faction`), `name`, `description`,
`icon.href`, `regions[].id`, optional `queue` mit `options[]` (`href`, `name`, `description`, `icon`).
Regionen (`BattleServerRegionCollection-v1`) brauchen `name`, `href` und `pingAddress`.

---

## 2. Was ist der Gefechtsserver?

### 2.1 Gleicher Code, andere Rolle

- `dust/app.py`, `CalculateRoleMask` (Z. 273): `elif _pyunreal.GIsServer and not _pyunreal.GIsClient:
  role |= APP_ROLE_BATTLESERVER`. Die Rolle hängt nur an den UE3-Globals, Python ist dasselbe.
- `dust/startmini.py`, `InitApp` (Z. 251): Wenn die Rolle `APP_ROLE_BATTLESERVER` ist, werden
  `GetBattleServices()` geladen: `battleServer`, `battleOrbitalClient`, `dataLogBattle`, `fittingBattle2`,
  `inventoryBattle`, `skillBattle`, `accountingBattle`, `userBattle`.
- `PS3-DustGame.ini`: `DefaultServerGame=DustGame.DustTeamGame_Commander`, `[DustGame.DustGameSession]
  mDefaultGameFlowIndex=2 / mDedicatedServerFlowIndex=3 / mEditorFlowIndex=4`. Der Dedicated-Ablauf ist
  im UnrealScript angelegt.
- `DustEngine-DedicatedServerCook.ini` unterscheidet sich von `PS3-DustEngine.ini` vor allem durch
  `Client=WinDrv.WindowsClient`, `Paths=..\..\DustGame\Content`, `Extensions=umap`. **Die Server wurden
  als Windows-Build gekocht.** Das passt zu `app.py` (`if sys.platform == PLATFORM_WIN32:
  if self.HasRole(APP_ROLE_SERVER): self.pumpWindowsMessages = True`) und zum Beenden per
  `os.kill(os.getpid(), signal.SIGINT)` in `battleServer`.

### 2.2 So arbeitete ein CCP-Gefechtsserver (`dust/battleServer.py`)

1. Start mit `launchconfig=<datei>` auf der Kommandozeile (`_ParseConfig`, Z. 354). Die INI hat
   mindestens die Abschnitte `[server] serveruri, username, password`, `[battle] battleuri` und
   `[mapurl] backendproxyaddr`. UE3 liest weitere Werte über `GetConfigSection` und
   `GetConfigSectionValue` (UnrealCallable), darunter vermutlich Karte und Spielmodus (**offen**).
2. UE3 meldet `OnBattleServerStartingFromUnreal`. Dann folgt `_LoginToBackend` (Z. 204): OAuth mit
   `scope = 'battleserver'` und `clientID 'internal'` (das Secret steht im Code), Benutzer und Passwort
   aus der Launch-Config.
3. Nach dem Login (`OnDustUserLogonNotification`, Z. 163): eigener Notification-Stream,
   `PUT serveruri {"status":"starting"}` (`BattleServerUpdate-v1`), `PUT battleuri`, `GET battle`
   (`BattleServerBattle-v1`), `GET members` (`BattleServerBattleMemberCollection-v1`), danach
   `Util.BattleServerLogin()` in UE3.
4. Für jedes Mitglied (`_MemberJoinedBattle`, Z. 287) erzeugt der Server zufällig eine 24-stellige
   `credential`, holt Charakter und Söldner (`Character-v1`, `Mercenary-v1`, `battleSkills`) und gibt
   über `PUT member {"team", "credential"}` (`BattleServerBattleMemberUpdate-v1`) die Credential ans
   Backend. **Das Backend leitet sie dann mit `OnBattleMemberConnect` an den Client weiter.** Wenn der
   Client mit `?credential=` verbindet, ordnet UE3 ihn über
   `GetDustCharacterURIFromCredential` (Z. 409, UnrealCallable) dem Charakter zu. Weitere
   UnrealCallables liefern Name, Rasse, Corp, Porträt und GM-Rechte.
5. Am Ende (`_CompleteBattle`, Z. 223): `POST battle['completed']` mit Gewinner, Kriegspunkten und
   verbrauchten Gegenständen. Das Backend berechnet Belohnungen, der Server schickt sie per UE3-RPC an
   die Clients (`OnEndOfMatchResults`). Nach `BATTLESERVER_ENDOFGAME_DELAY = 120` s beendet er sich.

### 2.3 Kann das PS3-Binary Server sein?

- **Als Dedicated Server (ohne Client): unwahrscheinlich.** Bei UE3 schaltet die Kommandozeile
  (`server <map>`) den Dedicated-Modus ein, auf Konsolen ist er meist nicht einkompiliert. CCP hat Windows
  gekocht. Ob die PS3-EBOOT `GIsClient=false` überhaupt zulässt, ist **offen** (EBOOT/Ghidra).
- **Als Standalone- oder Listen-Spiel: sehr wahrscheinlich.** In UE3 läuft jede Standalone-Partie mit
  `GIsServer` und `GIsClient`. Die Spiellogik (GameInfo, Spawns, Ziele) ist dann im Client aktiv. Dazu
  kommen die Belege aus Abschnitt 3 (Offline-Modus). Ob `?listen` auf der PS3 funktioniert, also
  andere Spieler sich verbinden können, ist **offen**. Die INIs konfigurieren
  `IpDrv.TcpNetDriver` aber auch für die PS3 (Timeouts, `NetServerMaxTickRate=30`).

---

## 3. Der eingebaute Offline-Modus

- `dust/login.py`: `OfflineLogin(loadMQ=True)` (Z. 99) ist **`@UnrealCallable`**. UE3 kann es also selbst
  aufrufen, etwa wenn das Spiel direkt auf einer Karte startet und `loadMQ=False` übergibt.
  `-autologinserver=offline` und `_UserLoginWithPassword` (Z. 240) führen ebenfalls dorthin.
- `dust/userClient.py`, `OfflineConnect` (Z. 238), Ablauf in `DoHackData`:
  `self._InitBattleServices()` → `_HackOfflineLoginData()` → `_HackOfflineClientData()` →
  `_HackOfflineBattleData()`. `_InitBattleServices` (Z. 293) macht
  `from startmini import GetBattleServices; self.app.InitServices(services)`. **Der Client lädt damit
  zur Laufzeit alle Gefechtsserver-Dienste in seinen eigenen Prozess.**
- `dust/userBattle.py`, `OfflineConnect` (Z. 32, ebenfalls UnrealCallable): legt für
  `NUM_OFFLINE_PLAYERS = 100` Charaktere ab ID 2100001611 Inventar (jeder Typ 999-mal), alle Skills auf
  Stufe 5 und eine Standardausrüstung aus `offline.offlineResourceFittings` an und ruft
  `battleServer.AddExtraRolesAsGM()` auf. 100 Plätze sprechen dafür, dass mehrere Spieler an einem
  Offline-Server getestet wurden, nicht nur einer.
- Die Offline-Handler, die wir in `catma_service` schon ausführen, liefern für Gefechte nur leere
  Listen und eine Region `local` mit `pingAddress 192.168.1.1`. Im Offline-Modus kam man also nicht
  über die Gefechtssuche ins Spiel, sondern über einen direkten Kartenstart (UE3-Konsole oder
  Kommandozeile).

### 3.1 Inhalte liegen lokal vor

- Spieldatenbank: 56 `DustGameType` (u. a. `gamemode_ambush_*` / `DustGame.DustSkirmishGame`,
  `gamemode_domination_*`, `gamemode_skirmish_*`, `gamemode_survival*` / `DustGame.DustSurvivalGame`
  mit Drohnenwellen, darunter **`gamemode_survival_infestation_1p`**, `gamemode_conquest` /
  `DustTeamGame_Commander`, `gamemode_playineditor`) und 33 `GalaxyLevel` mit Kartenname je Modus,
  z. B. `level_craters_bg_1`: Ambush `MN_Craters01_BG01_AmbA` (353889), Domination `…_DomB` (365195),
  Skirmish `…_SkB` (365340), OMS `…_OmsA` (364136).
- Die Kartenpakete selbst liegen in den PSARCs unter `COOKEDPS3_ARC`, z. B. `MN_CRATERS01_BG01_AMBA.XXX`,
  `…_DOMA/B`, `…_SKA/B`, `…_OMSA`, `MN_CRATERS01_SANDBOX.XXX`, `MN_VALLEY01_SK02.XXX`,
  `SHIPINTERIOR01_PROTOTYPE_*`, `WB_WARROOM_CA` (Kommandoraum). Nicht gefunden habe ich die
  `testmap_*`-Karten. Nichts muss heruntergeladen werden.
- KI: `[DustGame.DustAIProfileMgr]` in `PS3-DustGame.ini` (Ausrüstungen für KI-Pawns),
  `AITemplate` (Drohnen) und `BenchmarkStepSpawnAIPlayers` (`DustGame.DustBenchmarkTestStepSpawnAIPlayers`,
  8 KI je Seite). Es gibt also Bots, ob sie im Spiel auslösbar sind, ist **offen**.
- Cheat-Manager: `[DustGame.DustCheatManager] mCreateGameDefaultGameType=gamemode_playineditor,
  mCreateGameDefaultGameTypeWithGameModeMap=gamemode_skirmish`. Das deutet auf ein Cheat-Kommando
  „CreateGame“ hin. `DUSTGAME\CONFIG\CUSTOMCOMMANDS.TXT` (`God`, `SetMCCShield`, `IgnorePlayableArea`)
  zeigt, dass Konsolenbefehle mitgeliefert werden.

### 3.2 Unser Hebel

Über `client_patch\` (in `COMMON.SDAT`) können wir eigenen Python-Code im Client ausführen, aktuell den
Log-Forwarder. Damit gehen auch `dustUnreal.RunUE3Command(...)`, `userClient._InitBattleServices()`,
`userBattle.OfflineConnect()` und Ähnliches. Einschränkung: Der PS3-Build hat keinen Compiler für
`.py`-Quelltext. Code muss also als vorkompiliertes Bytecode-Objekt (`marshal`) ankommen. Reine
UE3-Konsolenbefehle sind dagegen nur Strings.

---

## 4. Mögliche Wege

| Weg | Idee | Belege | Hürden / offene Punkte | Aufwand | Risiko |
|---|---|---|---|---|---|
| **(d) Lokales Gefecht (Standalone)** | Client lädt eine Gefechtskarte lokal, Spiellogik läuft im Client, Gefechtsdienste per `_InitBattleServices` | Offline-Modus (Abschnitt 3), `OfflineLogin` als UnrealCallable, alle Karten lokal | Wie startet man den Kartenwechsel? (`CleanLoad <map>` / `open` / `Start`, offen). Erwartet UE3 Callbacks (`GetDustCharacterURIFromCredential`, Fittings), die im Online-Login fehlen? Ohne zweiten Spieler endet Ambush evtl. sofort, dann KI oder Survival nötig | **klein–mittel**: 1–3 Abende bis zu einem ersten Ergebnis, danach Feinschliff | mittel: Absturz oder Hänger beim Kartenladen. Rückweg über Neustart |
| **(b) Client als Host (Listen-Server)** | wie (d) mit `?listen`. Andere Clients bekommen über unseren CREST-Server `OnBattleMemberConnect` mit Host-IP:7777 | TcpNetDriver in der PS3-Config, Python-Gefechtsdienste laufen im Client, Credential-Mechanismus vorhanden | Listen-Support in der PS3-EBOOT (offen). Host-Python müsste die `battleServer`-Rolle sauber übernehmen (Credentials ans Backend). RPCS3-Netz zwischen zwei Instanzen/PCs (UDP 7777, ggf. RPCN-P2P). Der Host spielt mit, seine Leistung (Emulation) bestimmt den Tick | **mittel–groß**: Wochen | hoch, aber wo es scheitern würde, lässt sich früh messen |
| **(a) Zweite RPCS3-Instanz als Dedicated Server** | PS3-Binary im Server-Modus mit `launchconfig=` | Python-Code des Servers vollständig, Launch-Config-Format zum Teil bekannt | Dedicated Server auf der PS3 vermutlich nicht einkompiliert (CCP: Windows). Kommandozeilenargumente unter RPCS3 nur per EBOOT-Patch. Zwei Emulatoren kosten viel Leistung | groß, nur nach EBOOT-Analyse | **sehr hoch**, vermutlich unmöglich |
| **(c) Gefechtsserver nachbauen** | eigener Server mit UE3-Netzprotokoll und Dust-Spiellogik | – | UE3-Replikation aller DustGame-Klassen, Physik, Treffer, Ziele: alles nur im Binary | sehr groß (Mannjahre) | praktisch nicht machbar |
| *(a') Windows-Server von CCP* | Original-Dedicated-Server | Cook-INI belegt, dass es ihn gab | nicht veröffentlicht | – | nicht verfügbar |

Bei (b) und (d) liefert unser CREST-Server die Daten für Ergebnis und Belohnung: `POST battle.completed`,
`member.completed`, Lohn usw. Das ist Fleißarbeit in `crest_app.py`, aber kein Risiko.

---

## 5. Empfehlung und nächstes Experiment

**Reihenfolge:** zuerst (d) beweisen, dann (b) prüfen. (a) erst nach einer EBOOT-Analyse, (c) gar nicht.

### Experiment 1: Fake-Gefecht über den normalen Beitrittsweg (nur Serveränderungen)

Dafür ist kein Client-Patch nötig. Ziel: die ganze Kette Menü → `CleanLoad` testen und dabei sehen,
was `CleanLoad` mit einem **lokalen Kartennamen** macht.

1. `crest_app.py`: eigene Handler statt der leeren Offline-Antworten:
   - `/battles/theatres/`: ein Theater `{"key": "public", "name": "Test", "description": "…",
     "icon": {"href": …}, "regions": [{"id": …}]}` ohne `queue`, damit der Weg über die Gefechtsliste
     gewählt wird
   - `/battles/`: ein Gefecht mit `status: 3`, `teamSelect: false`, `mode.id: 353889`, `planet`,
     `system`, `constellation`, `region`, `attacker`/`defender`, `members.href`
   - `GET /battles/<id>/`: dasselbe Objekt (`Battle-v1`)
   - `POST /battles/<id>/members/`: Antwort `BattleMember-v1` (`href`, `character`, `battle`, `team`),
     danach in den Charakter-Stream: `OnBattleMemberJoined`, kurz darauf `OnBattleMemberConnect` mit
     `server.address`, `server.port`, `credential`, `team: "attacker"`, `battle.{id,href}`, `href`
2. **Variante A (Netzwerk-Probe):** `server = 127.0.0.1:7777`. Auf dem PC lauscht ein kleiner UDP-Logger
   auf 7777. Ergebnis: Wir sehen, ob und wie der Client zu verbinden versucht (UE3-Handshake), und
   den Befehl im `client.log` (`RunUE3Command: CleanLoad …`).
3. **Variante B (lokale Karte):** `server.address = "MN_Craters01_BG01_AmbA?game=DustGame.DustSkirmishGame?x"`,
   `server.port = 1`. Daraus wird `CleanLoad MN_Craters01_BG01_AmbA?game=…?x:1?credential=…`. Erwartung:
   Die Engine lädt die Karte lokal (Standalone). Im `client.log` sehen wir dann, welche Python-Callbacks
   UE3 anfragt und woran es scheitert, z. B. fehlende `battleServer`-Dienste.
4. Gelingt B bis zum Kartenladen, kommt als nächster Schritt ein kleiner Client-Patch:
   `userClient._InitBattleServices()` und `userBattle.OfflineConnect()` vor dem Kartenwechsel aufrufen
   und bei Bedarf Credential und Charakter-Cache für den eigenen Charakter vorbelegen.

Voraussetzung: Dienste neu starten, Spiel starten und im Menü „Gefecht suchen“ öffnen. **Das passiert nur
nach Absprache.** Der Code für Schritt 1 ist ein Abend Arbeit.

### Ergebnis Experiment 1 (2026-10-23)

Umsetzung: `dust_server/crest_app.py` (Abschnitt „Experiment 1“), Schalter in `dust_server/fake_battle.json`
(`enabled`, `variant`, wird bei jeder Anfrage neu gelesen), UDP-Logger auf Port 7777 in `listen_server.py`
(`kind: battle_probe` in `requests.jsonl`). Damit niemand im Menü drücken muss, hängt `client_patch/autoexec_ue3.py`
`-autologinbattle=LocalTest` an `sys.argv`. `battleClient3.OnQuitToMercQuartersNotification` tritt dann
beim Betreten der Söldnerunterkunft dem Fake-Gefecht bei. Bei `enabled: false` passiert nichts.

- **Kette Menü → `CleanLoad` funktioniert vollständig.** Ablauf im Log: `Autologin to battle: LocalTest` →
  `POST /battles/514001/members/` → `OnBattleMemberJoinedFromBackend` → `OnBattleMemberConnectFromBackend`
  → `OnProceedBattleConnectNotification` → `FadeOut` → `CleanLoad …?credential=…?Team=0?LightingMode=MOOD_DAY?DefaultArmor=352592`.
  Das Stream-Format und die Felder aus Abschnitt 1 stimmen also.
- **Variante A (`127.0.0.1:7777`):** Der Client spricht echtes UE3-UDP. Ab der ersten Sekunde nach `CleanLoad`
  schickt er etwa jede Sekunde ein 37-Byte-Paket (`0080052080c0030002…40`, das erste Byte zählt hoch: 00, 05 …)
  und dazwischen 2-Byte-Pakete (`0140`, `0240`, `0340` …), insgesamt rund 290 Pakete in 60 s. Nach genau 60 s
  (`InitialConnectTimeout=60.0`) kommt `OnClientLostConnectionFromUnreal('Your connection to the host has been lost.')`,
  dann `OnBattleTerminated` → `LoadMercQuarters`. **Dieses Zurückladen der Söldnerunterkunft hängt danach.**
  Python läuft weiter, aber `NotifyMapLoaded` kommt nie, das Bild steht.
- **Variante B (lokaler Kartenname):** `CleanLoad MN_Craters01_BG01_AmbA?gametype=gamemode_ambush_32p?dummy:1?…`
  zeigt den Ladebildschirm (RPCS3 öffnet `MOVIES/TIP_TEXT_W_ICON_MASTER_1.BIK`). Danach gibt es minutenlang
  **keinerlei** Aktivität: kein UDP, kein HTTP, kein UE3→Python-Aufruf, kein `NotifyMapLoaded`. `CleanLoad`
  ist also kein allgemeines `open <URL>`. Vermutlich verbindet es immer erst zu einem Server, bevor es
  lädt (die Karte schickt der Server), oder es wartet auf ein Ereignis, das nur der Server-Ablauf auslöst.
- `TTY.log` zeigt „Shipping Build“ und eine leere `CommandLine:`. UE3-eigene Logs gibt es nicht.

Folgerungen:
1. Ein lokales Gefecht geht **nicht** über den normalen Beitrittsweg. Für Weg (d) brauchen wir einen anderen
   UE3-Befehl (`open`/`Start <map>?…`, wie `dustUnreal.ReturnToLoginScreen` ihn mit `Start loginscene?…` benutzt).
   Den können wir über `dustUnreal.RunUE3Command` aus einem Client-Patch absetzen. Das ist der nächste Test,
   etwa `Start MN_Craters01_BG01_AmbA?gametype=gamemode_ambush_32p`, vorher `userClient._InitBattleServices()`.
2. Für Weg (b) und jeden echten Server ist jetzt klar, was an Port 7777 ankommt: ein UE3-Verbindungsaufbau,
   den nur eine laufende UE3-Engine (Host-Client oder Dedicated Server) beantworten kann.
3. Nach einem gescheiterten Verbindungsversuch bleibt das Laden der Söldnerunterkunft hängen. Bei Tests muss
   danach neu gestartet werden.

### Ergebnis Experiment 2: direkter Kartenstart (2026-10-23)

Werkzeug: `client_patch/dustdevhook.py` fragt in der Söldnerunterkunft `GET /dev/commands/`
(`dust_server/dev_commands.json`) ab und führt jede neue `revision` einmal aus. Aktionen sind `ue3`,
`init_battle_services`, `offline_battle_connect`, `mark_in_battle`, `call` (Dienstmethode, auch
`__setattr__`) und `sleep`. Neue Befehle brauchen also keinen Neustart.

- `init_battle_services` startet alle acht Gefechtsdienste im Client, und `userBattle.OfflineConnect` läuft.
  `inventoryBattle` fängt die doppelte Registrierung bewusst ab.
- `Start MN_Craters01_BG01_AmbA?gametype=gamemode_ambush_32p` lädt die Karte, Zustand Fighting, HUD.
  `dustClient.ForceRespawn()` läuft per UE3-RPC an `battleServer.SpawnCharacterWithFitting` und zurück.
  Nach etwa 30 s kommt aber „DEFEAT – Clone reserves depleted“ (auch mit `?Team=0` und mit
  `gamemode_survival_infestation_1p`).
- **`gametype=gamemode_playineditor`** (DustGameInfoPIE) wartet auf `Login::OfflineLoginFinished`. Nach
  `userClient.offlineConnectFinished = True` folgen `GetSpawnFittingAdapter`, `OnSpawnPlayerFromUnreal`,
  `CheckOutFittingForCharacter` mit der echten Ausrüstung, dann `OnMatchBegin` und **ein Spawn in der Welt
  mit vollem HUD**. Kein Match-Ende.
- Problem: **Es fehlt das Gelände.** Mit `MN_Craters01_BG01_AmbA` gibt es nur graues Nichts, mit
  `MN_Craters01` erscheinen Gebäude und das Deployment-Menü, aber der Spieler fällt durch („Tap X to
  activate Inertia Dampener“). `dustClient.battle` mit `mode.id` ändert daran nichts (`GetBattlePlanetID`
  wird nicht abgefragt). Gelände (MegaTerrain `MT_DATA_MN_CRATERS01…`), Terraforming (`…_TF-*`) und
  Socket-Komponenten werden vermutlich über eigene URL-Optionen oder Streaming-Befehle geladen. Das ist
  der nächste offene Punkt, am besten mit der EBOOT (Strings zu `Terraform`, `MegaTerrain`, `Socket`, `Mood`).

### Ergebnis Experiment 3: begehbare Karte (2026-10-23)

Die EBOOT lässt sich mit `rpcs3.exe --headless --decrypt <EBOOT.BIN>` entschlüsseln (Ergebnis liegt lokal in
`research/eboot_0319/`, nicht im Repo). Die Strings zeigen: Die Kartenlade-Routine kennt neben `GAME=`/`GAMETYPE=`
die Option **`mega`** (siehe Korrektur unten: MegaServer, nicht MegaTerrain). Beim Netz-Willkommen schickt der Server `Terraform=%s` (`terraforming=`).
Dust-eigene Funktionen zur Kartenkomposition sind u. a. `ADustGameInfoPIE.LoadNonGameModeLevels`,
`ADustTeamGame.BeginLoadGameModeLevel/InitOutpostLevels/GetSocketFromLevel` und
`UDustGameEngine.AddDynamicOutpostSocket/SetIsWaitingForOutpostNamesFromBackend/SetDesiredMood`.

Eine Karte besteht aus mehreren Paketen (`COOKEDPS3_ARC/MN_CRATERS01.PSARC`): Basis `MN_CRATERS01`, `_MT`
(MegaTerrain), `_BSP`, `_VI`, `_BG0x_SM` (Bauten je Schlachtfeld), `_BG0x_AMBA/DOMA/SKA/OMSA` (Spielmodus-Ebenen)
und fast alles zusätzlich in Terraforming-Varianten `_TF-DEFAULT/-DESERT01/-BARREN01/…`.

Befund im Spiel:
- `Start MN_Craters01?mega?Terraform=Default?gametype=gamemode_playineditor?…`: Gelände **mit Kollision**,
  begehbar, aber schwarz (ohne Textur).
- **`Start MN_Craters01?mega?Terraform=Desert01?LightingMode=MOOD_DAY?gametype=gamemode_playineditor?Team=0?Name=DustPlayer`:
  vollständige, texturierte und beleuchtete Karte mit Anlage, Geländern und Bergen. Laufen funktioniert, die
  Figur spawnt mit der Ausrüstung des Charakters (hier Sturmgewehr).** Screenshot: `docs/battle_craters_desert.png`.
- Derselbe Aufbau mit `gametype=gamemode_ambush_32p` beginnt das Match, aber es spawnt keine Figur. Der Python-RPC
  `SpawnCharacterWithFitting` kommt an, UE3 fragt danach aber keine Ausrüstung ab, und das Bild bleibt schwarz.
  In echten Gefechten wählt man den Spawnpunkt auf der Übersichtskarte (`ui/overviewMap.py`), die sich hier nicht
  öffnet.
- Die nötigen Schritte stehen als Revision in `dust_server/dev_commands.json`: Gefechtsdienste,
  `offline_battle_connect`, `userClient.offlineConnectFinished = True`, `mark_in_battle`, `Start …`.
- Bedienung: Der Launcher („GO“) und die Charakterauswahl brauchen Cross (`X`, kurz halten), sonst bleibt der
  Login vor der Söldnerunterkunft stehen.

Korrektur (Experiment 4): `mega=` gehört zu `UMegaServerConnection`/`UMegaServerDriver` und ist für das
Gelände **nicht** nötig. Das Gelände kommt über `Terraform=`.

### Ergebnis Experiment 4: Lichtartefakte und Ambush-Modus (2026-10-24)

**Lichtartefakte** (gesprenkelte, gestrichelte helle Bänder an Lichtkegeln und Rampen): Das ist ein Darstellungsfehler
von RPCS3, kein Fehler der Kartenkomposition. `MSAA: Disabled` änderte nichts. **`Write Color Buffers: true`** in
`D:\rpcs3\config\custom_configs\config_NPUB30643.yml` behebt es. Danach sind die Szenen sauber bei etwa 35 FPS.
Sicherung der vorherigen Konfiguration: `config_NPUB30643.yml.before_msaa_test`. Screenshot: `docs/battle_craters_desert_wcb.png`.

**Ambush läuft lokal.** Im UnrealScript (`DUSTGAME.XXX`) steht das Entwickler-Rezept von `DustCheatManager.CreateGame`:
`CleanLoad <map>?gametype=…?DustUserID=…?DustCharID=…?gameModeLevel=…?listen?bfid=0?loadDefaultOutpost`, danach
der Befehl `Terraform <Variante>`. Weitere Optionen dort: `?battleID=`, `?LoadOfflineMode=1`.
Funktionierender Start (in `dev_commands.json` als Standard hinterlegt):

```
Start MN_Craters01?gametype=gamemode_ambush_32p?gameModeLevel=MN_Craters01_BG01_AmbA?bfid=365271?loadDefaultOutpost?Terraform=Desert01?LightingMode=MOOD_DAY?Team=0?Name=DustPlayer
```

- `bfid` ist die Typ-ID des `GalaxyLevel` (hier `level_craters_bg_1` = 365271), `gameModeLevel` der `mapName`
  aus dessen `gameModes` für den gewählten Spielmodus.
- Ohne `gameModeLevel`/`bfid` gibt es keine Spawnpunkte („DEPLOYMENT FAILED: Uplink Lost“, leere Übersichtskarte),
  und nach `forceCompositionTime` = 30 s endet das Match mit „DEFEAT – Clone reserves depleted“.
- Die Deploy-Übersichtskarte öffnet sich nicht von selbst. `uiSvcOverviewMap.OnRequestOpenMenu(1)` öffnet sie
  (`ChangeOverviewMapState(1)` scheitert an `CanOpenMenu()`, solange keine Figur lebt). Sie zeigt das echte
  Schlachtfeld, Clones 50 : 50, Timer 15:00. „Smart Deploy“ (Triangle) spawnt die Figur über den normalen Weg
  `SpawnCharacterWithFitting` → `OnSpawnCharacterConfirmed` → `OverviewMap.SelectSpawnPoint` →
  `GetSpawnFittingAdapter`/`CheckOutFittingForCharacter`.
- Das Match läuft danach normal weiter (getestet über mehrere Minuten), die Karte ist komplett: Wüste, Felsen,
  Anlagen, Fahrzeuge. Screenshot: `docs/battle_ambush_craters.png`.
- Gegner fehlen noch: `EnableCheats`, `AddAI`, `AddAIAttacker`, `SpawnBots 4`, `SetNumBots 4` bewirkten nichts
  (Verteidiger bleiben bei 0 Spielern). `SetMinPlayersPerTeam 0` und `SkipForceComposition` ebenfalls ohne Wirkung.

Nachtrag: Die Lichtartefakte (gestrichelte helle Bänder auf Böden und Rampen, seltsame Wolken bzw. Nebel) treten
auch mit `Write Color Buffers` weiter auf. Die Ursache ist noch offen.

Nachtrag 2 (2026-10-26): **`Read Depth Buffer: true`** und **`Write Depth Buffer: true`** beheben die Wolkendecke,
die über allen 3D-Ebenen lag, und das blaue Leuchten hinter der Karte. Die Unreal Engine 3 rendert Nebel, Wolken und
Bloom gegen eine Kopie des Tiefenpuffers, die ohne diese Optionen fehlt. Die weißen Striche auf beleuchteten Böden
bleiben. Sie richten sich nach der Fläche und verteilen sich bei jeder Bewegung neu. Ohne Wirkung blieben:
`Handle RSX Memory Tiling`, `Strict Texture Flushing`, `Shader Precision: Ultra` (starker FPS-Einbruch),
`SPU XFloat Accuracy: Accurate` und `Strict Rendering Mode`. `Accurate RSX reservation access` zusammen mit
`Accurate SPU DMA` lässt das Spiel zuverlässig in den Merc Quarters abstürzen, mit OpenGL stürzte es beim Betreten
des Matches ab. Die Striche sind vorerst zurückgestellt und ein Fall für die RPCS3-Entwickler.
Sicherung vor diesen Tests: `config_NPUB30643.yml.before_gfx_test`.

### Ergebnis Experiment 5: Dev-Controller und Gegner (2026-10-24)

Analyse von `DUSTGAME.XXX` mit eigenen Lesern für Namen, Exporte, Importe und Funktionsflags
(`research/tools_local/upk.py`, `execs.py`, nicht im Repo). Nach dem Bytecode-Ende `0x53` folgen iNative (2 Byte),
Präzedenz (1 Byte), FunctionFlags (4 Byte) und bei Netz-Funktionen RepOffset (2 Byte). `FUNC_Exec` = 0x200.

- `DustTeamGame.GetPlayerControllerClassFromOption` liest **`?PlayerControllerClass=`**. Mit
  `?PlayerControllerClass=DustGame.DustDevPlayerController` bekommt der Spieler den Entwickler-Controller.
- Konsolenbefehle über `Util.ExecConsoleCommand` erreichen den PlayerController (`Suicide` wirkt). Mit dem
  Dev-Controller wirken dessen Exec-Funktionen, z. B. `SetCloneReservesForTeam 777 0` (HUD zeigt 777). Liste
  u. a.: `SpawnAI(npcID, teamNum)`, `SpawnByType(typeName, isEnemy, SpawnDistance, …)`,
  `SpawnInstallationByType(typeName, SpawnDistance, Team)`, `SetCloneReservesForTeam`, `SetMinPlayersPerTeam`,
  `SwitchTeam`, `TeleportToSpawnPoint`, `StartWaveNow`/`GotoNextWave` (Survival), `IgnorePlayableArea`.
  `DustCheatManager` (`CreateGame`, `CG`, `SimpleCreateGame`, …) ist im Release-Build nicht erreichbar.
- **Gegner-Objekte entstehen:** `SpawnInstallationByType inst_dronehive_smallhunter_all 2000 1` setzt ein
  Drohnen-Nest (Team 1) vor den Spieler, mit Feind-Markierung im HUD. Es nimmt Schaden (Zielinfo „Armor 4595“).
  `SpawnByType drone_medium_grey 1 1500` erzeugt einen Drohnen-Pawn (UE3 fragt dafür die Slots von 355207 bei
  Python ab). Beide sind bisher **passiv**: keine Angriffe, keine Drohnenwellen im Ambush-Modus.
- `SpawnAI <npcID> <team>` (npcID = `DustNPCDefinition` aus der DB, z. B. 355316 `qa_npc_01` „QA Drone –
  Standard Assault“ oder 355354 `drone_hunter_medium_assaultrifle`) erzeugt nichts. Keine einzige Karte enthält
  KI-Spawnpunkte (`DustAISpawnPoint`), nur `DustTeamPlayerStart` in den Outposts.
- `DustSvcAutobot.SpawnBots` wird nur aus `DustDevPlayerController.SpawnAutoBots` aufgerufen. Das ist ein
  Server-Event, kein Konsolenbefehl, und sonst ruft es niemand auf.
- `DustTeamGame.Login` vergibt Offline-Charakter-IDs (`GetNextOfflineCharID`). Mehrere menschliche Spieler über
  `?listen` sind im Offline-Modus also vorgesehen (Weg b).
- Tastenbelegung im Gefecht: Feuern = R1 (`E`), Smart Deploy = Triangle (`V`), Karte schließen = Circle (`C`).

### Ergebnis Experiment 6: Survival-Modus (2026-10-24)

- `gamemode_survival_infestation_1p` startet auf Craters (`gameModeLevel`/`bfid` wie beim Ambush). Die
  Deploy-Karte öffnet sich von selbst, die Figur deployt automatisch, Clones 12 : 99999.
- Nach etwa 21 s endet das Match mit **„VICTORY“**: Jede Welle setzt ihre Nester an Kartenmarkierungen
  (`m_DroneHiveSpawnTag` = `wave0`, `wave1_1` …). Die gibt es in keiner ausgelieferten Karte (Scan aller PSARCs),
  also sind die Wellen leer und gelten als geschafft. `PauseStageTimer` und von Hand gesetzte Nester
  (`SpawnInstallationByType inst_drone1p_wave_1 …`) ändern daran nichts.
- Die Survival-/Drohnen-Modi waren nach Erinnerung des Nutzers und nach Datenlage (Karten `testmap_Infest…` nie
  ausgeliefert) nie öffentlich spielbar. Ausgeliefert waren Ambush (Team-Deathmatch), Skirmish und Domination.
  **Bots als Gegner gab es in DUST nicht.** Der naheliegende Weg zu echten Gefechten ist daher Mehrspieler
  (Weg b: `?listen`, Offline-Charaktere über `DustTeamGame.Login`/`GetNextOfflineCharID`).
- Noch ungetestete Idee für Übungsgegner: Die CATMA-Datenbank liegt im Python-Speicher des Clients. Würde man
  vor dem Kartenstart die Wellen-Tags auf vorhandene Actor-Tags umbiegen (Actor-Tag = Klassenname, z. B.
  `DustWorldCenter` in der Spielmodus-Ebene), könnten die Wellen echte Nester spawnen. Ob UE3 die Werte zur
  Laufzeit aus Python liest, ist offen.

### Ergebnis Experiment 7: Startargumente und Benchmark-Modus (2026-10-24)

- RPCS3 reicht Argumente ans Spiel durch, wenn sie hinter der EBOOT nach `--` stehen:
  `rpcs3.exe --no-gui EBOOT.BIN -- -benchmarktest …`. Steht `--` vor der EBOOT, stürzt RPCS3 ab („Range check
  failed“), ohne `--` wertet RPCS3 die Schalter selbst aus („Unknown options“). Im TTY-Log erscheinen sie als
  `CommandLine: …`, in Python als `sys.argv`. `tools/start_dust.ps1` und `restart_all.ps1` haben dafür `-GameArgs`.
- `-benchmark` ist UE3s Standard-Schalter und ändert am Ablauf nichts. **`-benchmarktest`** schaltet Dusts
  Benchmark-Testclient ein (`GIsBenchmarkTest`): Er lädt die Söldnerunterkunft sofort ohne Charakterauswahl, mehrere
  Python-Dienste scheitern ohne Charakter, und der Client meldet „disconnected because of an internal error“.
- Die vier Benchmark-Fälle der DB (`bt_benchmark_test_01`, `…_tgtrace`, `…_stress`) bestehen aus Warte-,
  Prüf- und Konsolenschritten (`EnterBenchmarkTestBattle`, `ForceSpawnAtPlayerStartWithTag benchmark`, `shot`,
  `LoadMercQuarters`, `QuitBenchmarkTestBattle`). Der Schritt `SpawnAIPlayers1` (8 KI je Seite) kommt in keinem Fall
  vor. Der Benchmark-Modus ist damit kein Weg zu Bots.
- Bot-Code im Spiel, Stand jetzt: `DustDevPlayerController.SpawnAI` (keine KI-Spawnpunkte in den Karten),
  `DustSvcAutobot.SpawnBots` (nur über ein Server-Event erreichbar), `DustBenchmarkTestStepSpawnAIPlayers` (in keinem
  Benchmark-Fall). Für die nativen Teile davon ist die EBOOT-Analyse mit Ghidra der nächste Schritt.
- Vollbild: `restart_all.ps1 -Monitor \\.\DISPLAY3 -Fullscreen` startet RPCS3 mit `--fullscreen --game-screen <n>`.
  RPCS3 zählt den Hauptmonitor als 0, dann die übrigen in Windows-Reihenfolge. Das Skript läuft DPI-bewusst.

### Ergebnis Experiment 8: native Bot-Funktionen (2026-10-24)

Werkzeuge (alle unter `research/`, nicht im Repo): Ghidra 12.1.4 headless (`research/ghidra/dust514_eboot`,
Analyse 2 h 20 min, Skript `scripts/DumpDust.java` zum Dekompilieren), eigene Leser für die Native-Tabelle
(`tools_local/native_table.py`: 3578 Einträge `{UTF-16-Name, Funktionsdeskriptor, 0}`, TOC `r2 = 0x1c8a420`), Capstone
und ein RPCS3-Speicherabzug (Utilities → Dump Guest Memory, `tools_local/memdump.py`).

- Die Exec-Stücke lesen nur die Parameter und rufen virtuell weiter: `execServerSpawnAI` → vtable `+0x654`,
  `execSpawnBots` → `+0x164`, `execFindAISpawnPoint` → `+0x47c`, `execAddAI` (DustSpawner) → `+0x3f0`.
- Statisch ließen sich die vtables nicht zuordnen (keine RTTI, und Ghidra legt für `lis`/`addi`-Konstanten keine
  Referenzen an). Haltepunkte im RPCS3-Debugger greifen mit dem LLVM-Recompiler nicht.
- Gelöst über den Speicherabzug: UE3-Namenseinträge (`FNameEntry`: Index·2, HashNext, Name) liefern den Namensindex.
  Objekte tragen den Namen bei `+0x2c` und die Klasse bei `+0x34`, der vtable-Zeiger steht bei `+0`. Default-Objekte
  (`Default__Klasse`) liefern die vtable jeder Klasse, auch ohne Instanz auf der Karte.

| Funktion | vtable | Slot → Code | Inhalt |
|---|---|---|---|
| `DustDevPlayerController.ServerSpawnAI` | `0x19683f0` | `+0x654` → `0x20980` | leer (`blr`) |
| `DustSvcAutobot.SpawnBots` | `0x196ffe0` | `+0x164` → `0x20980` | leer (`blr`) |
| `DustSvcAutobot.IsActive` | `0x196ffe0` | `+0x17c` → `0x75fc8c` | liefert nur ein globales Flag |
| `DustSkirmishGame.FindAISpawnPoint` | `0x196f520` | `+0x47c` → `0x26ec0` | `return 0` |
| `DustSpawner.AddAI` | `0x1980da0` | `+0x3f0` → `0x26ec0` | `return 0` |

**Ergebnis:** Im Release-Build ist die gesamte KI-Spawn-Logik herauskompiliert. Die Funktionen existieren nur als
leere Stubs. Damit sind Bots über Konsolenbefehle oder Startargumente nicht erreichbar. Die passiven Drohnen-Nester
erklärt das ebenfalls, denn sie erzeugen Drohnen über `DustSpawner.AddAI`. Gegner gibt es realistisch nur über
Mehrspieler (Weg b). Bots selbst zu bauen hieße, KI-Code per EBOOT-Patch nachzurüsten, und das ist nicht machbar.

Nächste Schritte:
1. Gegner: Drohnen aktiv machen (Survival-Modus `gamemode_survival*` mit `StartWaveNow`/`GotoNextWave` auf
   einer vollständigen Karte, selbst gesetzte Nester per `SpawnInstallationByType`), oder herausfinden, ob Cheats im Release-Build aktivierbar sind (`AllowCheats`, `AddCheats`) bzw. wie
   `DustSvcAutobot.SpawnAutoBots`/`ADustDevPlayerController.ServerSpawnAI` erreichbar sind, oder ein zweiter Client
   per `?listen` (Weg b, Port 7777).
2. Kartenwahl aus der Spieldatenbank ableiten (`GalaxyLevel` → `mapName`, `gameModes[].mapName`, `terraforming`,
   `moods`) und als Gefechtsliste im CREST-Server anbieten, sodass der normale Beitrittsweg (Experiment 1) den
   Start-Befehl auslöst statt `dev_commands.json`.
3. Match-Ende, Belohnungen und Rückkehr in die Söldnerunterkunft testen.

### Ergebnis Experiment 9: Mehrspieler mit zwei RPCS3-Instanzen (2026-10-24)

Aufbau auf einem Rechner:

| | Host | Client 2 |
|---|---|---|
| RPCS3 | `D:\rpcs3` | Kopie `D:\rpcs3_b` (6,2 GB, ohne Logs und Speicherabzüge) |
| CREST | Port 8080, `dev_commands.json` | Port 8081 (`SAKE.INI`), `dev_commands_8081.json` |
| Anmeldung | PSN über RPCN (eigenes Konto) | Dev-Autologin `-autologinserver=127.0.0.1:8081`, dazu NP über einen **lokalen RPCN-Server** mit Testkonto |
| Netz | Bind-Adresse `0.0.0.0` | Bind-Adresse `127.0.0.2` |
| Rolle | Listen-Server: Ambush-Rezept plus `?listen` (UDP 7777) | `CleanLoad 127.0.0.1:7777?credential=…?Team=1` |

Hürden und Lösungen:
- **PSN-Pflicht beim Start:** Mit PSN-Status „Disconnected“ bleibt Client 2 schon im nativen Startcode bei
  „Connection to PlayStation Network was lost“ hängen, also vor Python. Dasselbe RPCN-Konto zweimal geht nicht,
  weil RPCN eine zweite gleichzeitige Anmeldung ablehnt. Lösung: der quelloffene RPCN-Server 1.12.1
  (`research/rpcn/`, nur `127.0.0.1:31313`) mit einem lokalen Testkonto. Angelegt wurde es mit
  `research/rpcn/create_account.py` (Protokoll 34, Befehl `Create`). Nur die Kopie zeigt darauf; das echte Konto des
  Hosts bleibt unberührt.
- **Portkonflikt:** Beide Instanzen binden den P2P-Port UDP 3658 (RPCS3-Absturz „Failed to bind DGRAM socket to
  3658“). Lösung: In der Kopie steht `Net → Bind address: 127.0.0.2`.
- **UDP 7777:** Der Probe-Logger aus Experiment 1 belegte den Port. Er liegt jetzt auf 17777.
- **Credential-Prüfung des Hosts:** Beim Beitritt ruft der Host
  `BattleServer::GetDustCharacterURIFromCredential(credential)` auf. Unbekannte Credentials führen zum Abweisen
  („Your connection to the host has been lost“). Ohne `?credential=` stürzt der Python-Aufruf mit einem `TypeError`
  ab. Lösung: neue Dev-Hook-Aktion `battle_member`. Sie legt auf dem Host einen `BattleCharacterCache` mit
  fester Credential, Team und Charakter-ID an, so wie `_MemberJoinedBattle` es bei einer Backend-Notification tut.
  Client 2 tritt danach über `dustUnreal.OnProceedBattleConnectNotification` mit derselben Credential bei.
- **Vollbild hing:** Im Vollbild blieb der Host beim Hinweis „Precompiling shader interpreter variants“ stehen,
  obwohl das Spiel dahinter lief. Im Fenstermodus trat das nicht auf.

Ergebnis:
- Client 2 lädt die Host-Karte. Beide Deploy-Karten zeigen je einen Spieler pro Team (Blau 1, Rot 1).
- Client 2 spawnt per Smart Deploy und steht im Spiel. Der Host bestätigt den Spawn per
  `OnSpawnCharacterConfirmedNotification` (Bild `battle_mp_client2_ingame.png`).
- `PauseStageTimer` hält den Missions-Timer an. Ohne ihn endete das erste Match nach rund 16 Minuten mit
  „DEFEAT – Mission timer expired“.
- **Offen:** Nach dem Beitritt spawnt der Host-Spieler selbst nicht mehr, seine Ansicht bleibt in der
  Übersichtskamera (`battle_mp_host_stuck.png`). Im Battle-Server kommt nur ein einziges
  `SpawnCharacterWithFitting` an, und zwar für die ID 2100001611, die Client 2 erhalten hat. Vermutlich bekommen
  beide Spieler dieselbe Offline-ID (`GetNextOfflineCharID`), sodass die Anfrage des Hosts verloren geht.
  Nächster Schritt: Host zuerst spawnen lassen, dann Client 2 beitreten lassen, oder die ID-Vergabe in
  `DustTeamGame.Login` untersuchen.
- **Nachtrag (gleicher Tag):** Spawnt der Host zuerst und tritt Client 2 erst danach bei, sind beide gleichzeitig
  im Spiel (`battle_mp_both_host.png`, `battle_mp_both_client2.png`). Beide Spawn-Anfragen tragen aber weiter die
  ID 2100001611, auch mit Host-Charakter 3 (2100002246) und Client-Charakter 2 (2100001612). Die CREST-Charakterwahl
  spielt also keine Rolle. Nach `GetDustCharacterURIFromCredential` fragt der Host `GetCharacterID` nicht ab; die
  ID aus `battle_member` wird nicht benutzt. `GetNextOfflineCharID` (vtable-Slot `0x430` → `0x757578`) zählt nur
  einen globalen Zähler (`0x1cbdd68`, Start 2100001611) hoch. Vermutung: Jeder Prozess vergibt seinem Spieler
  diese erste Offline-ID, und die Spawn-RPC trägt die ID des Clients. Folge: Bestätigungen wie
  `OnSpawnCharacterConfirmed` gehen an den ersten Controller mit dieser ID. Mit Host-zuerst-Reihenfolge klappt
  es, für mehr als zwei Spieler muss die ID-Vergabe aber noch gelöst werden (UnrealScript `DustTeamGame.Login`
  bzw. die Spawn-RPC untersuchen).
- **Gelöst (2026-10-25):** Disassembliert mit `research/tools_local/uscript.py` (Bytecode-Leser für das
  UE3-Paket `DUSTGAME.XXX`). `DustTeamGame.Login` kennt zwei Zweige. Ist `mSessionServerID != -1`, holt es
  per Credential URI, `GetCharacterID`, Name, Rasse, Corp, Rang, Porträt und Geschlecht vom Battle-Server. Sonst
  ruft es `GetLocalCharacterID(out id)` auf und nur bei `false` `GetNextOfflineCharID()`. Auf einem Listen-Server
  liefert `GetLocalCharacterID` bei **jedem** Login die lokale Offline-ID des Host-Prozesses, daher die
  Kollision. Die Spawn-RPC (`DustPlayerController.InvokeSvcMethodOnBattleServer`) nimmt `PRI.GetCharID()`.
  `mSessionServerID` setzt `InitGame` aus der URL-Option **`?battleID=`**. Das Host-Rezept startet die Karte daher
  mit `?listen?battleID=514001?credential=<Host>` und registriert per `battle_member` sich selbst
  (2100001611, Team 0) und Client 2 (2100001612, Team 1). Ergebnis: getrennte IDs, Name „Host Mercenary“ in der
  Squad-Liste, beide Spawns kommen mit eigener ID an, und Client 2 kann auch zuerst spawnen. Das Assert
  `NetMode == Dedicated` im Credential-Zweig bleibt im Release-Build folgenlos. `DustAccessControl.PreLogin`
  prüft die Credential nur bei `bfid > 0`.
- Spawnt ein anderer Spieler, während der Host auf der Deploy-Karte steht, schließt sich die Karte beim Host (HUD
  mit Übersichtskamera, kein Spawn möglich). `uiSvcOverviewMap.OnRequestOpenMenu(1)` öffnet sie wieder. Der
  Dev-Hook macht das jetzt selbst: Er patcht `BattleServer.SpawnCharacterWithFitting` und öffnet die Karte
  6 Sekunden nach dem Spawn eines fremden Spielers wieder, falls sie vorher offen war.

**Beitritt über die Gefechtssuche (2026-10-25):** Der manuelle Beitritt per Dev-Befehl ist ersetzt.
- `fake_battle.json` hat die Variante `listen` (Ziel `target_listen` = Host-Adresse und UDP 7777). Beim Beitritt
  (`POST /battles/514001/members/`) vergibt der CREST-Server je Spieler eine Credential, eine eigene
  Gefechts-Charakter-ID (ab `first_member_id` 2100001612), eine eigene URI (`/battlecharacters/<id>/`) und das Team
  `listen_team`. Danach schickt er wie CCPs Backend `OnBattleMemberJoined` und nach 8 Sekunden
  `OnBattleMemberConnect` mit Adresse und Credential.
- Der Host fragt `GET /dev/battle/members/` alle 3 Sekunden ab und registriert jede neue Credential per
  `battle_member` in seinem Battle-Server.
- Ein Client tritt mit dem Startargument `-autologinbattle=LocalTest` beim Betreten der Merc Quarters selbst bei;
  von Hand geht es über die Gefechtssuche. Der Client-Patch erzwingt das Argument nicht mehr, sonst würde der Host
  seinem eigenen Gefecht beitreten.
- Das Battle-Objekt braucht `mode.name`, sonst bricht die Übersicht (`overviewPanel`) mit `KeyError` ab und es
  gibt keine Deploy-Auswahl.

Getestet mit zwei Instanzen: Client 2 tritt per Autologin bei, spawnt als 2100001612, die Host-Karte öffnet sich
wieder, und der Host spawnt als 2100001611.

- Der Server schickt `OnBattleMemberConnect` erst, wenn der Host die Spielerliste mit dem neuen Spieler abgeholt
  hat. Während der Host eine Karte lädt, läuft sein Python nicht, die Abfrage kommt also erst danach. Ein Client,
  der mitten ins Laden verbindet, brachte den Host vorher zum Absturz.
- Die Host-Karte schließt sich erst, wenn der fremde Spieler wirklich im Spiel ist (in Skirmish bis zu
  12 Sekunden). Der Hook beobachtet deshalb 30 Sekunden lang und öffnet die Karte, sobald sie zugeht, außer der
  Host spawnt in der Zeit selbst.

**Host ohne Tastendrücke (2026-10-25):** Der Client bringt alles mit. Mit `-autologinserver=<CREST>` setzt
`login.py` `attemptedAutoLogin`, und der Launcher schließt sich ohne GO (`launcherPanel._UpdateTick`).
`-autologincharindex=<n>` wählt den Charakter (`characterCreation2._AutomateCharacterLoginIfRequested`). Die NP-
Anmeldung über RPCN läuft weiter im Hintergrund. Aufrufe:

    tools/restart_all.ps1 -Monitor \\.\DISPLAY3 -GameArgs "-autologinserver=127.0.0.1:8080 -autologincharindex=0"
    tools/start_dust.ps1 -Rpcs3 D:\rpcs3_b\rpcs3.exe -GameArgs "-autologinserver=127.0.0.1:8081 -autologinusername=dust2 -autologincharindex=1 -autologinbattle=LocalTest"

Der Host ist damit nach rund einer Minute in den Merc Quarters und startet per Dev-Rezept die Karte. Client 2 tritt
ohne Eingriff bei. Gespielt werden muss nur noch das Absetzen.

**Weitere Spielmodi (2026-10-25):** Kennungen aus CATMA (`GalaxyLevel.gameModes`, `DustGameType`), umschaltbar mit
`dust_server/set_host_mode.py <modus>`:

| Modus | `gametype` | `gameModeLevel` (`bfid`) | Ergebnis |
|---|---|---|---|
| Ambush | `gamemode_ambush_32p` | `MN_Craters01_BG01_AmbA` (365271) | läuft mit zwei Spielern |
| Skirmish | `gamemode_skirmish_4obj_32p` | `MN_Craters01_BG01_SkB` (365271) | läuft mit zwei Spielern: MCC, Ziele A–D, je 150 Klone (`battle_mp_skirmish_host.png`) |
| Domination | `gamemode_domination_32p` | `MN_Craters01_BG01_DomB` (365271) | läuft mit zwei Spielern: Ziel A, MCC (`battle_mp_domination_client2.png`) |
| Acquisition | `gamemode_domination_2` (`DustDominationGame`, Punkte laufen nach 300 s ab) | `MN_Highland01_BG01_Dom20A` (365818) | lädt, Spawn klappt, aber der Spieler steht in einer roten Zone („Ground unit unsafe zone“), Punkte 000/000 (`battle_mp_acquisition_host.png`); Startposition bzw. Team-Zuordnung noch offen |
| Ambush OMS | `gamemode_ambush_oms_32p` | `MN_Craters01_BG01_OmsA` (365271) | noch nicht getestet |
| Planetary Conquest | `gamemode_conquest` (`DustTeamGame_Commander`) | keine Karte mit diesem Modus in `GalaxyLevel` | braucht Corporations, Bezirke und Clone-Logistik im Backend, nicht im Client |

**Bekannter Absturz:** Wechselt ein laufender Host in einen *anderen* Modus (z. B. Ambush → Skirmish,
Skirmish → Domination), stürzt er einige Sekunden nach dem Laden ab: Lesezugriff auf Adresse 0 in der Funktion bei
`0x8cb534`, die ein Null-Objekt bekommt. Derselbe Modus lässt sich im laufenden Host neu starten. Für einen anderen
Modus wird der Host neu gestartet; die Clients treten danach per Gefechtssuche wieder bei.

Ablauf zum Nachstellen:
1. Server neu starten (Ports 8080 und 8081, Probe 17777), danach den lokalen RPCN-Server starten
   (`research/rpcn/rpcn.exe`).
2. Host: `tools/start_dust.ps1 -Monitor \\.\DISPLAY3 -Width 1600 -Height 900`. Das Rezept in `dev_commands.json`
   registriert per `battle_member` den Mitspieler und startet die Karte mit `?listen`.
3. Client 2:
   `tools/start_dust.ps1 -Rpcs3 D:\rpcs3_b\rpcs3.exe -GameArgs "-autologinserver=127.0.0.1:8081 -autologinusername=dust2"`.
   Sobald die Merc Quarters geladen sind, die `revision` in `dev_commands_8081.json` erhöhen.
4. Nach Änderungen an `client_patch/` beide Installationen patchen: `tools/patch_common_sdat.py` und
   `tools/set_toc_size.py COMMON.SDAT`, für die Kopie mit `DUST_GAME_DIR=D:\rpcs3_b\…\DUSTGAME`.

**Test Null-Renderer (Vorstufe für einen Host ohne GPU, z. B. im Docker-Container):** Host mit `Renderer: "Null"`
für Bild und Ton gestartet. Login und CREST laufen, das Fenster meldet 60 FPS. Ab dem Launcher wird Python aber
nicht mehr getaktet (über 3 Minuten ohne Logzeile), und RPCS3 meldet alle 12–25 Sekunden „Display queue was
discarded while not empty“. Das Spiel kommt mit dem Null-Renderer praktisch nicht voran, der Launcher reagiert
nicht auf Eingaben. Für einen Host ohne Grafikkarte bleiben Vulkan per Software (lavapipe/SwiftShader) mit
minimaler Auflösung oder ein Server mit (kleiner) GPU. Die Konfiguration ist zurückgestellt
(`config_NPUB30643.yml.before_null`).

**Test Software-Vulkan (lavapipe):** Mesa 26.2.4 für Windows (pal1000/mesa-dist-win, `research/mesa/`), per
`VK_DRIVER_FILES` als einziger Vulkan-Treiber. RPCS3 rendert damit auf `llvmpipe (LLVM 23.1.2, 256 bits)`,
eingestellt waren 720x480, 25 % Auflösungsskalierung und kein MSAA. Ergebnis: Vor dem Spielstart baut RPCS3 die
6650 Shader-Interpreter-Varianten, und zwar auch mit „Async Shader Recompiler“. Nach 16 Minuten stand es bei
708 (Hochrechnung über 2 Stunden), bei 0,04–1,3 FPS, nur 1–2 genutzten Kernen eines Ryzen 9 5900X und 18 GB
RAM für RPCS3. Der Python-Teil des Spiels startete in der Zeit nicht. Abgebrochen; Konfiguration zurückgestellt
(`config_NPUB30643.yml.before_lavapipe`).

Nachtrag (2026-10-25): Der Wert „Async Shader Recompiler“ war ungültig. RPCS3 meldete
`cfg::try_to_enum_value(...): invalid enum` und fiel auf den Standard mit Interpreter zurück. Die gültigen Werte
für `Shader Mode` sind „Legacy Recompiler (single-threaded)“, „Async Recompiler (multi-threaded)“, „Async Recompiler
with Shader Interpreter“ und „Shader Interpreter only“. Mit „Async Recompiler (multi-threaded)“ entfällt die
Vorkompilierung. Ergebnis mit lavapipe (Host, Dev-Autologin): Python nach 4 Minuten, Merc Quarters nach
6,5 Minuten, 0,06–0,34 FPS, rund 20 GB RAM, 1–2 genutzte Kerne. Eine Minute später stürzt RPCS3 im
lavapipe-Treiber ab (Ausnahme `0xC0000008` in `RtlEnterCriticalSection`, aufgerufen aus `vulkan_lvp.dll`). Selbst
ohne den Absturz wäre der Host bei unter einem Bild pro Sekunde unbrauchbar, denn ein UE3-Listen-Server rechnet das
Spiel im selben Takt, in dem er rendert.

Folgerung für einen Host im Rechenzentrum: Weder Null-Renderer noch Software-Vulkan sind brauchbar.
Realistisch ist ein Server mit (kleiner) GPU und Vulkan-Treiber, z. B. ein Root-Server mit Nvidia- oder
AMD-Karte, Docker mit GPU-Durchreichung und Xvfb. Offen bleibt, ob die Interpreter-Varianten auf der Platte
zwischengespeichert werden. Dann wäre die lange Vorkompilierung nur einmal nötig.

Für einen zweiten PC gilt dasselbe. Statt 127.0.0.1 trägt man dann die LAN-Adresse des Hosts ein (CREST-URL in
`SAKE.INI` bzw. `-autologinserver`, Ziel des `CleanLoad`). Mit einem eigenen RPCN-Konto entfällt der lokale RPCN-Server.

**Null-Renderer gelöst (2026-10-25):** Der Hänger ist ein RPCS3-Fehler, keiner des Spiels. Damit braucht der Host
**keine GPU**.
- Befund: Mit `Renderer: "Null"` schafft das Spiel genau ein Bild alle 12,016 s (721 VBlanks). Dazwischen pollt der
  `RenderingThread` mit `appSleep(0.0002)` einen RSX-Fence (EBOOT `FUN_006649d8`/`FUN_006648ac`: Label-Wert ≥ Fence),
  und die RSX-FIFO kommt nur in kleinen Schritten voran, obwohl der RSX-Thread fast untätig ist. Mit
  `Vblank Rate: 600` sinkt die Zeit auf 1,2 s pro Bild. Die Wartezeit hängt also an den VBlanks und nicht an der
  Rechenleistung. Der Fenstertitel „FPS: 60“ zählte nur Flips.
- Ursache: `GSRender::flip()` (`rpcs3/Emu/RSX/GSRender.cpp`), das nur der Null-Renderer benutzt, ruft anders als
  Vulkan und OpenGL nicht `rsx::thread::flip(info)` auf. Dadurch bleibt nach dem ersten per Syscall angeforderten
  Flip `async_flip_requested.emu_requested` gesetzt. `do_local_task` ruft deshalb bei jedem Durchlauf
  `handle_emu_flip()` auf, und mit `Frame limit: Auto` schläft die RSX dort jedes Mal bis zum nächsten 60-Hz-Takt.
  Zwischen den Flips arbeitet sie nur wenige Befehle ab. Upstream ist das auch am 2026-10-25 (`f848fd1e1`) noch so.
- Workaround ohne eigenen Build: `Frame limit: "Off"` oder `PS3 Native`. Dann schläft `handle_emu_flip()` nicht, und
  der Host ist nach rund 1 Minute in den Merc Quarters, startet die Ambush-Karte als Listen-Server (UDP 7777) und
  tickt Python flüssig. Nachteil: Er flippt dauernd (Fenstertitel ~450.000 „FPS“, RSX-Thread ~80 %,
  `_gcm_intr_thread` ~30 % CPU). Die SPURS-Kerne laufen mit je ~80 % wie auf einer echten Karte. Konfiguration:
  `D:\rpcs3\config\custom_configs\config_NPUB30643.yml.null_host` (aktiv bleibt die Vulkan-Konfiguration).
- Eigentlicher Fix (eine Zeile, `rpcs3_patches/null-renderer-flip.patch`): `GSRender::flip()` ruft
  `rsx::thread::flip(info)` auf. Dafür muss RPCS3 selbst gebaut werden (Windows: VS 2022 + Qt 6; Linux: im
  Docker-Image für den Server).
- Mehrspieler-Test (15:09–15:15): Host `D:\rpcs3` mit `config_NPUB30643.yml.null_host` (Null, `PS3 Native`) ist
  nach 75 s auf der Ambush-Karte. Client 2 (`D:\rpcs3_b`, Vulkan) tritt per `-autologinbattle=LocalTest` über die
  Gefechtssuche bei (`POST /battles/514001/members/` um 15:12:13), lädt die Host-Karte, spawnt als 2100001612
  (`SpawnCharacterWithFitting` beim Host, `OnSpawnCharacterConfirmed` beim Client) und steht mit 26 FPS im Spiel
  (`battle_mp_nullhost_client2.png`). Der Dev-Hook öffnet die Host-Deploy-Karte wie gewohnt wieder. Nicht geprüft:
  Bewegung und Kampf über längere Zeit, mehr als ein Client.
- Docker (2026-10-25, `docker/README.md`): RPCS3 aus dem Quellcode mit dem Patch, `--headless`, Null-Renderer,
  `Frame limit: Auto`, unter Docker Desktop/WSL2. Der Host läuft ohne Flip-Schleife bis zur Karte, und Client 2 tritt
  bei und spawnt (`battle_mp_docker_client2.png`). Zwei Stolpersteine: Docker Desktops Host-Netz leitet keine
  UDP-Antworten zurück (daher `compose.desktop.yaml`), und ein Neustart des CREST-Servers lässt das Python des Hosts
  sterben, während RPCS3 weiterläuft. Deshalb prüft der Watchdog jetzt `/dev/host/heartbeat/`.

### Web-Admin im Spiel geprüft (2026-10-25)

Der CREST-Server hat jetzt eine Weboberfläche (`dust_server/admin.py`, Port 8088, Bedienung im README). Geprüft
mit dem Host in `D:\rpcs3`:

- **News:** Die im Admin gesetzte Nachricht des Tages steht im Launcher (untere Zeile). Der Reiter NEWS zeigt
  `readMe.txt`. Die Dokument-Links tragen jetzt die Änderungszeit im Namen, damit der Client geänderte Texte holt.
- **Markt und Wallet:** Mit 999 ISK für die Plasma Cannon sowie 777.777 ISK und 5.000 AUR im Admin zeigt der
  Marktplatz genau diese Werte (`admin_market_ingame.png`). Der ISK-Markt war vorher leer. Jetzt kommen Gruppenbaum
  und Preise aus CATMA (`catma_service/catalog.py`, `GET /catalog`). Geöffnet per Dev-Rezept auf Port 8081
  (`call uiSvcMarket.OpenMarketWithItem [350916]`), weil Tastendrücke in dieser RPCS3-Konfiguration nicht ankommen.
- **Moduswechsel:** Ambush → Skirmish gespeichert, dann „Restart host“ im UI (`tools/restart_host.ps1` startet nur
  die Host-Instanz neu). Der Host kommt mit Skirmish hoch: Ziele A–D, je 150 Klone (`admin_host_skirmish.png`).
  Zurück zu Ambush per „Save & apply“, während der Host läuft: Das UI vergibt keine neue Revision und zeigt
  „restart needed“. Der Host läuft ohne Absturz weiter. Nach „Restart host“ läuft Ambush mit je 50 Klonen und Timer
  (`admin_host_ambush.png`). Das Status-Feld „Running“ zeigt jeweils den Startbefehl, den der Host geholt hat.
- Ein Neustart des CREST-Servers trennt laufende Clients (Benachrichtigungsstream unbekannt →
  `NOTIFICATION_STREAM_DISCONNECTED`).

### Live-Kombinationen und Kollision fern vom Host (2026-10-26)

**Karten und Modi der Live-Version.** CATMA (`GalaxyLevel.gameModes`) markiert jede Kombination mit
`mProductionReady` und `useInMatchmaking`. Sind beide gesetzt, lief sie im Matchmaking (18 von 33 Levels, z. B.
Impact Ridge mit Ambush `AmbA`, Ambush OMS, Domination `DomB`, Skirmish `SkB`). Nie live waren Testmaps, die
`_dup`-Kopien ohne Namen (Ausnahme: `level_highland_bg_1_dup`/`_dup1` tragen beide Flags), alle 48p-Varianten,
Craters BG01 `DomA`/`SkA`, Highland BG02 `SkA`, Ambush OMS auf Highland, SandBox, Valley und ShipInterior. Die
Host-Seite im Admin zeigt deshalb nur noch Live-Kombinationen; das Kästchen „Unofficial“ blendet den Rest ein.
In Ambush gibt es keine festen Spawnpunkte: Man setzt per Smart Deploy (Triangle) an einer vom System gewählten
Stelle ab oder an Drop Uplinks. Das ist so gewollt.

**Sockel-Belegung.** Eine Karte hat Sockel für Bauten (Craters: 45 klein, 12 mittel, `OP01`/`OP03` groß). Der
Dedicated Server bekam deren Belegung aus seiner `launchconfig`-INI, Abschnitt `[sockets]`
(`DustTeamGame.LoadSockets` → `DustServerConfig.GetSection` → `battleServer.GetConfigSection`). `DustServerConfig`
fragt aber nur bei `NetMode == 1` (Dedicated) nach, auf dem Listen-Server kommt nichts an. Mit `loadDefaultOutpost`
laden die Sockel die Vorgabe des Karteneditors. Für Impact Ridge ändert das nichts: Dort gibt es laut CATMA nur
`Backdrop01` (Stargate) und `OP03` (Vorgabe `OP_GA_Research01L` = erster CATMA-Kandidat). Auf Karten mit kleinen
und mittleren Sockeln (z. B. Highland) bleiben diese bei uns vermutlich leer.

**Problem: falsche Kollision fern vom Host (bestätigt).** Client 2 spawnt teils in Geometrie (kann dann nicht
springen), immer an denselben Stellen, und fällt beim Laufen einen Meter unter die sichtbare Karte. Der Host selbst
hat diese Fehler nicht. Läuft die Host-Figur zu Client 2, stimmt die Kollision dort; spawnt der Host danach woanders,
fällt Client 2 sofort durch die Karte.

Ursache: Jeder Outpost besteht aus einem groben Paket (`OP_GA_RESEARCH01L.XXX`) und der vollen Detailstufe mit
genauer Kollision (`OP_GA_RESEARCH01L_LOD0_TF-DESERT01.XXX`). Position und Kollision rechnet der Server. Ein
Listen-Server der Unreal Engine 3 streamt nur um den Blickpunkt seines eigenen Spielers, fern davon gilt die grobe
Kollision. Client 2 sieht die volle Detailstufe, weil sein Client sie lädt. Vor dem Spawn verschiebt
`DustPlayerController.ServerTriggerStreaming` zwar den Controller zum Spawnpunkt, gewartet wird aber nur auf das
Streaming des Clients (`ClientStartCheckStreaming` → `CheckStreamingStatus` → `ServerOnStreamingFinished`). Der
Docker-Host ist genauso betroffen. Die UE3-Streaming-Befehle (`StreamLevelIn`, `OnlyLoadLevel` …) fehlen im
Release-Build. Der Namensbaustein `_LOD0` steht genau einmal als ASCII-String in der EBOOT.

**Entscheidung: beim Listen-Server bleiben** und ihn per RPCS3-Patch so ändern, dass der Host `_LOD0` lädt wie der
Dedicated Server im Live-Spiel. Ein eigener Server bräuchte dieselbe Kollision (Pakete lesen, UE3-Bewegungsphysik)
und dazu die Replikation aller DustGame-Klassen, das sind Mannjahre. Nächste Schritte:
1. Ghidra: Verweise auf den String `_LOD0` suchen und herausfinden, wann ein Outpost seine `_LOD0`-Ebene lädt.
2. Variante 1 testen: Der Host lädt `_LOD0` aller Outposts unabhängig von seiner Position. Risiko: 256 MB RAM der
   PS3. Speicher messen, auch auf dem Docker-Host mit Null-Renderer.
3. Falls der Speicher nicht reicht, Variante 2: zusätzlich um die Positionen der anderen Spieler streamen (mehrere
   Blickpunkte wie im Splitscreen).
Abbruchkriterium: Die Entscheidung ist im nativen Code nicht zu finden, oder der Speicher reicht auch für Variante 2
nicht. Dann den eigenen Server neu bewerten.

**Schritt 1 erledigt (Ghidra, 2026-10-26).** Der String `_LOD0` liegt bei `0x17e1b84` und hat genau einen Verweis
(`0x41f0a8`) in `FUN_0041ec70`. Das ist UE3s `UWorld::UpdateLevelStreaming(ViewFamily)` (Ausgabe:
`research/ghidra/out_lod0_decomp.txt`). Aufbau:
- `param_1` = GWorld (`DAT_01cb0fe8`), WorldInfo `+0x3e4/+0x3e8` = `StreamingLevels`. Pro `ULevelStreaming`:
  `+0x3c` Flag-Bits, `+0x40` `PackageName` (FName), `+0x48` `LoadedLevel`.
- Mit `ViewFamily` läuft die Schleife über alle Views, nimmt `View+0x2f0` (ViewOrigin) und ruft die virtuellen
  `ShouldBeLoaded(Loc)` (vtable `+0x150`) und `ShouldBeVisible(Loc)` (`+0x154`). Ohne `ViewFamily` gilt (0,0,0).
- Die `_LOD0`-Stelle: Ist eine Ebene `X` nicht geladen, baut der Code `X + "_LOD0"` und lädt `X` nicht, solange ein
  Streaming-Eintrag mit diesem Namen existiert und selbst noch nicht geladen ist.
- Aufrufer: `FUN_0022a480` (Viewport-Draw) baut die ViewFamily nur aus den lokalen Spielern (`GEngine+0x474`,
  `CalcSceneView` = `FUN_0031a658`). Das ist der Grund, warum der Host nur um die eigene Figur streamt.
  `FUN_00270264` (Engine-Tick) ruft `UpdateLevelStreaming(NULL)`, wenn `DAT_01d1d1b8 == 1` (vermutlich Dedicated).
  `FUN_0042433c` ist das blockierende Flush-Streaming.

**Korrektur nach dem Speicherabbild (2026-10-26).** Im Abbild vom 2026-10-24
(`D:/rpcs3/guest_memory_dumps`, ausgewertet mit `research/tools_local/memdump.py`) sind alle 180 Streaming-Ebenen
`ULevelStreamingKismet` (vtable `0x191dc58`, `ShouldBeLoaded` = Flag-Bit 23 von `+0x3c`, `ShouldBeVisible` = Bit 22).
`DAT_01d2d264` ist 1. **`X_LOD0_n` ist der grobe Proxy und überall geladen.** Die volle Ebene `X_n` und der Ton
`X+AU_n` sind nur bei Outposts in Host-Nähe geladen (z. B. `OP_GA_Research01L_44`, `CS_GA_RelayStat01S_51`). Die
Bezeichnungen weiter oben sind in diesem Punkt vertauscht. Die Engine-Funktion entscheidet also nichts, sie liest
nur die Flags. Ein pauschales Erzwingen in `FUN_0041ec70` würde auch die alternativen Hintergründe laden
(`MN_Craters01_BG02/03`, `SandBox`, `BSP` …).

Die Flags setzt DUSTs Outpost-LOD-Manager `FUN_0085ed78`. Pro Outpost-Socket gibt es eine LOD-Liste (Einträge von
0x10 Byte: Ebene plus Unterebenen), Index 0 ist der `_LOD0`-Proxy. Geladen und sichtbar (`|= 0xc00000`) werden alle
Einträge mit `Index <= Socket+0x20`, alle anderen werden entladen (`&= 0xff3fffff`). `Socket+0x20` ist der Ziel-Index
aus der Distanz zum Host-Blickpunkt. Höhere Stufen kommen erst, wenn die vorige sichtbar ist (Bit 30).

**Patch-Entwurf Variante 1:** [`rpcs3_patches/host_full_outpost_lod.yml`](../rpcs3_patches/host_full_outpost_lod.yml)
ersetzt bei `0x85f12c` `lwz r4,0x20(r24)` (`80980020`) durch `lis r4,0x7fff` (`3c807fff`). Dann lädt der Host jede
Stufe jedes Outposts, aber keine anderen Kismet-Ebenen. Nur beim Host aktivieren. Noch ungetestet: Speicher, Ladezeit
vor dem Spawn, Kollision bei Client 2 fern vom Host. Variante 2 (statt fester Stufe die Distanz zum nächsten Spieler)
würde in der Distanzberechnung des Managers ansetzen, nicht in `FUN_0022a480`.

Eingetragen und aktiviert ist der Patch nur in `D:\rpcs3` (`patches\NPUB30643_patch.yml`, `config\patch_config.yml`,
Sicherungen `*.before_lod`). `D:\rpcs3_b` bleibt unverändert. Testablauf:
1. Dienste und Host: `tools/restart_all.ps1 -Label lod_patch -GameArgs "-autologinserver=127.0.0.1:8080 -autologincharindex=0"`,
   dann den lokalen RPCN-Server `research/rpcn/rpcn.exe` für Client 2.
2. In `D:\rpcs3\RPCS3.log` muss `PAT: Applied patch (… description='Listen host: load all outpost LODs'` stehen.
3. Host-Rezept läuft durch, Host spawnt zuerst. Danach Client 2:
   `tools/start_dust.ps1 -Rpcs3 D:\rpcs3_b\rpcs3.exe -GameArgs "-autologinserver=127.0.0.1:8081 -autologinusername=dust2 -autologincharindex=1 -autologinbattle=LocalTest"`.
4. Host bleibt stehen, Client 2 spawnt fern vom Host bzw. läuft zu einem fernen Outpost: kein Sturz durch die Karte,
   kein Spawn in Geometrie, Springen geht.
5. Speicher: im Host-Log auf Speicherfehler und Abstürze achten. Dann beim Host Utilities → Dump Guest Memory und
   `python -I research\tools_local\streaming_levels.py`. Ohne Patch (Abbild vom 2026-10-24) haben 3 von 55
   Outpost-Sockets die volle Ebene geladen, mit Patch sollten es alle sein.
Zurück: in RPCS3 den Patch im Patch-Manager abschalten oder die `*.before_lod`-Dateien zurückkopieren.

**Erster Test (2026-10-26, Ambush auf `MN_Craters01_BG02_AmbA`).** Das Log meldet den Patch als angewendet. Der Host
war nach ~90 s auf der Deploy-Karte, ohne Speicherfehler, mit rund 4–4,5 GB Prozessspeicher wie Client 2. Abbilder aus
dem laufenden Prozess (`research/tools_local/live_dump.py`, geht auch mit `--no-gui`): Der Host hat alle 55 vollen
Outpost-Ebenen geladen und sichtbar (vorher 3), Client 2 hat wie erwartet nur 4 um sich herum (`CS_GA_PowCore01S_15`,
`UC_GA_LandingP01M_14`, `UC_GA_Reactor01M_12`, `CB_GA_StarGate01_61`). **Trotzdem hängt Client 2 beim Spawn in der
Luft.** Das Streaming auf dem Host erklärt dieses Symptom also nicht mehr.

**Ursache des Hängens (Speicherabbilder vom 2026-10-26, `research/tools_local/uobjects.py`).**
- Der Streaming-Handshake ist es nicht: `DustPlayerController.Dead.DoRestartPlayer` ruft `RestartPlayer` erst nach
  `mClientReadyToSpawn` (gesetzt von `ServerOnStreamingFinished`). Der Spawn lief laut Log durch.
- Pawn von Client 2 (`DustPawnContent_1`; `Controller.Pawn` = `+0x1d8`, Actor `Location` = `+0x54`, `Physics` =
  Byte `+0x94`, `Base` = `+0xa0`): Auf dem Host steht er mit `PHYS_Walking` auf `StaticMeshActor_0` aus
  `CS_GA_PowCore01S_LOD0_15`, also auf dem Proxy. Auf dem Client hat er `PHYS_Falling` ohne `Base`, 5 Einheiten tiefer.
- Derselbe Proxy-Actor hat auf dem Host `bCollideActors` (`+0xb4` Bit 1) und `CollideActors` der Komponente
  (`+0x128` Bit 22), auf dem Client beides nicht. Auf dem Client ist die Proxy-Kollision genau bei seinen drei
  nahen Outposts aus, auf dem Host nur bei zwei Outposts in Host-Nähe.
- Mechanismus: Das Überblend-System `FUN_0099aa18` geht über alle Level und überblendet pro Cluster zwischen Proxy
  und Detail. Ein Zähler 0..31 läuft in Richtung Detail, wenn das Bit in `level+0x314` gesetzt ist (Cluster nah am
  eigenen Blickpunkt). `FUN_00995d58` blendet den Proxy aus (`+0xb0` Bit 2, `bHidden`), und `FUN_001a6158`
  (Kollisions-Update) nimmt einem ausgeblendeten Actor die Kollision. Jede Instanz entscheidet nach ihrem eigenen
  Blickpunkt. Der Host behält fern von sich die Proxy-Kollision, der Client hat an seiner Position nur Details.
- Nebenbefund: `FUN_0085fef0` berechnet die LOD-Zielstufe. Im Dedicated-Pfad (`DAT_01d1d1b8 == 1`,
  `DAT_01d1d1b4 == 0`) setzt sie `socket+0x20 = Anzahl Stufen`, lädt also alles, wie Patch-Zeile 1.

**Patch 0.2:** zusätzlich `0x99aaf0` `li r24,-1` → `li r24,1` (`3b000001`). Jeder Cluster gilt als nah, der Host
blendet überall auf Detail und nimmt den Proxies die Kollision. Eingetragen in `rpcs3_patches/host_full_outpost_lod.yml`
und beim Host.

**Test 2 (2026-10-27, gleiche Karte): Spawns funktionieren.** Drei Spawns von Client 2 quer über die Karte, alle
normal, kein Hängen. Host 12–16 FPS, rund 4,8 GB Prozessspeicher. Abbild des Hosts: alle 55 vollen Ebenen geladen,
alle 54 `_LOD0`-Proxies ohne Kollision (vorher 52 mit).

**Offen: verschachtelte Cluster.** Das Überblend-System gibt es auch innerhalb der vollen Outpost-Ebenen. Beispiel
`UC_GA_Reactor01M_12`: Bei Client 2 sind 4 StaticMeshActors sichtbar und kollidieren, auf dem Host sind dieselben 4
ausgeblendet (`+0xb0` Bit 2) und ohne Kollision. Insgesamt kollidiert auf dem Host nur noch 1 von 92
StaticMeshActors der vollen Ebenen (Test 1: 55). „Jeder Cluster ist nah“ ist für die Outpost-Proxies richtig, für
diese inneren Cluster zu viel. Folge vermutlich: Auf dem Server fehlen einzelne Hindernisse, durch die man laufen
oder schießen könnte. Saubere Lösung: Die Nah-Bitmaske `level+0x314` wird in `FUN_0099ac80` (`0x99af8c`, `0x99af98`,
`0x99afb0`) und `FUN_0099b1bc` (`0x99b320`) geschrieben. Dort „nah“ setzen, wenn irgendein Spieler nah ist, und die
zweite Zeile von Patch 0.2 wieder entfernen.

**Test 3 (2026-10-27): Terrain hängt am Blickpunkt.** Client 2 fiel immer an derselben Stelle am Outpost
`CS_GA_SecScan01S_41` durchs Haupt-Terrain (`MegaTerrain_0` aus `MN_Craters01_MT`). Ursache auf dem Client:
`Read/Write Depth Buffer` war nur beim Host eingeschaltet. Nach dem Einschalten in `D:\rpcs3_b` (Sicherung
`config_NPUB30643.yml.before_depth`) fällt er nicht mehr durch. Die Terrain-Höhen entstehen also auf der GPU und
werden über den Tiefenpuffer zurückgelesen. **Jeder Client braucht diese Einstellung.**

Danach spawnte Client 2 halb in einem Haus und lief gegen eine unsichtbare Wand, die ihn etwa 50 cm zurücksetzte.
Laut `pawn_state.py` standen beide Seiten auf `MegaTerrain_0`, aber etwa 93 Einheiten verschieden hoch (Client
65679.8, Host 65586.6). Der Host hatte keine eigene Figur, seine Kamera war weit weg. Als der Host-Spieler neben
Client 2 stand, war die Wand weg und die Höhen stimmten (65683.5 / 65683.3). **Der Host berechnet das Terrain nur um
seine eigene Kamera genau.** Fern davon nutzt der Server grobe Höhen. Im Betrieb hat der Host keine Figur, also
braucht es eine Lösung im Code: Der Host muss das Terrain an den Positionen aller Spieler genau berechnen (wie
Variante 2). Die Terrain-Daten fehlen nicht: Die CELL_ENOENT-Meldungen für `…MEGATERRAINDATA` und
`…MEGATERRAINDATA_FLAT.MTFLATDATA` sind nur der erste Suchversuch als lose Datei. Die Dateien liegen in
`MT_DATA_MN_CRATERS01_MT.COOKED__MT_CRATERS01_MTLG.PSARC` bzw. `MT_EXTRA.PSARC` (44 MTFLATDATA, auch alle
`CS_GA_…`), und beide Archive werden geöffnet. Fehlende oder nachzubauende Dateien sind also nicht die Ursache.

**MegaTerrain-Kollision (Analyse 2026-10-27, Einstiegspunkte).** Die Terrain-Kollision besteht aus rund 200
Kacheln `MegaTerrainCollisionComponent` (Outer `MegaTerrain_0`, vtable `0x198f568`; `+0xa0` Kachelecke, `+0xdc`
Kachelmitte mit Höhe), aufgebaut wie ein Quadtree. Nahe am Betrachter sind die Kacheln 2048–4096 Einheiten groß,
fern davon 65536, dort sind die Höhen entsprechend grob. Zuständig ist der `MegaTerrainManager` (vtable
`0x1991a98`, eigener Code ab `0x81e000`):
- `FUN_0081ffb4`: geht pro Terrain-Teil über `GEngine.GamePlayers` (`DAT_01caffd8+0x474/+0x478`, nur lokale
  Spieler), nimmt den 2D-Abstand zu `LocalPlayer+0x94/+0x98` und ruft `FUN_00815548(abstand, teil)` (wählt die
  Feinheit). Remote-Spieler kommen nicht vor.
- Ebenso über die lokalen Spieler laufen `FUN_007f9b54` (nutzt `PlayerController.Pawn`), `FUN_007fb450` und
  `FUN_007f7b0c` im Code der Kollisionskomponente (`0x7f7000–0x806000`).

Lösungsideen: (a) In `FUN_0081ffb4` statt der lokalen Spieler alle PlayerController der Welt durchgehen
(`WorldInfo.ControllerList`, Pawn-Location `+0x54`) und den kleinsten Abstand nehmen. Das braucht eine Code-Höhle,
ist aber die saubere Variante. (b) Schneller Versuch: Den Abstand vor dem Aufruf von `FUN_00815548` auf 0 setzen,
dann ist überall die feinste Stufe aktiv. Risiko: Speicher und Rechenzeit. Ein ähnlicher Durchlauf ist für die
Überblend-Cluster sinnvoll (`FUN_0099ac80`), damit die zweite Zeile von Patch 0.2 entfallen kann.

**Patch 0.3 (Entwurf 2026-10-27, ungetestet): Variante (a) für Terrain und Überblendung.** Zwei Code-Höhlen über
den RPCS3-Patchtyp `calloc` (code_alloc): `[ calloc, <hook>, n ]` ersetzt den Befehl am Hook durch einen Sprung in
n neue Plätze, dahinter steht der Rücksprung nach Hook+4. Die nächsten n Einträge füllen die Plätze der Reihe nach
(ihr Offset zählt nicht), ein `jumpl`-Eintrag wird dort zum `bl` auf eine feste Adresse. Den überschriebenen Befehl
muss die Höhle selbst wiederholen. Die Patch-Zeilen erzeugt `research/tools_local/cave_asm.py`.
- Ermittelte Offsets (Host- und Client-Abbild vom 2026-10-27 09:29): `WorldInfo.ControllerList` `+0x4f4`,
  `WorldInfo.PawnList` `+0x4f8`, `Pawn.Controller` `+0x1f4`, `Pawn.NextPawn` `+0x1f8`,
  `Controller.NextController` `+0x1e4`, `Actor.WorldInfo` `+0xec`. WorldInfo im nativen Code:
  `GWorld` (`*0x1cb0fe8`) `+0x50` (PersistentLevel) → `+0x3c` (Actors.Data) → `[0]`.
- Terrain: `FUN_00815548(abstand, teil)` setzt das Feld `+0xa8` auf das Minimum aus seinem alten Wert und der
  Stufe zum Abstand (`(abstand + 10000) * 2.5e-5`). `FUN_008154f0` setzt es vorher pro Tick auf `0x7fffffff`.
  Weitere Aufrufe verfeinern also nur. Höhle 1 sitzt bei `0x820088` (direkt nach `FUN_008152e8`, Teilmitte bei
  `0x70/0x74(r1)`, Teil in `r26`). `r27`/`r28` sind dort frei. Sie geht über `PawnList` und ruft
  `FUN_00815548(2D-Abstand, teil)` für jeden Pawn auf, danach `lis r27,0x1cb` (Original).
- Überblendung: In `FUN_0099ac80` liefert `bl FUN_01600890` bei `0x99ae94` den quadrierten Abstand zwischen den
  Cluster-Bounds (`r3 = r1+0x7c`) und dem Blickpunkt (`r4`). Höhle 2 ersetzt diesen Aufruf durch das Minimum über
  Blickpunkt und alle Pawn-Positionen (eigener Stackrahmen 0x90, sichert `r30`/`r31`). Ein Cluster ist damit nah,
  wenn irgendein Spieler nah ist. Die zweite Zeile von Patch 0.2 (`0x99aaf0`) ist in 0.3 entfernt.
- Beim Host eingespielt (2026-10-27): `D:\rpcs3\patches\NPUB30643_patch.yml`, Sicherung mit 0.2
  `NPUB30643_patch.yml.before_lod03`. `patch_config.yml` bleibt unverändert, weil RPCS3 nach dem Patch-Namen aktiviert.
- Testplan: im Log auf `PAT: Applied patch` achten, dann
  wie Test 2 und 3 spawnen. Prüfen: (1) Kein Hängen in der Luft. (2) Auf dem Host kollidieren in
  `UC_GA_Reactor01M_12` dieselben StaticMeshActors wie bei Client 2 (`uobjects.py`, `+0xb0` Bit 2). (3) Am Haus
  von Test 3 ist die Wand weg, und `pawn_state.py` zeigt auf beiden Seiten dieselbe Höhe, während die Host-Kamera
  weit weg ist. (4) FPS und Speicher des Hosts mit Test 2 vergleichen.
- Risiken: `jumpl` aus der Höhle zu einer fernen Adresse (RPCS3 baut den Sprung selbst). Ob RPCS3 den Rücksprung
  korrekt setzt, steht erst im Test fest. Stürzt der Host ab oder friert er ein, zuerst nur Höhle 2 oder nur Höhle 1
  aktiv lassen. Zurück auf 0.2: beide `calloc`-Blöcke durch die alte Zeile `0x0099aaf0` ersetzen.
- Noch nicht abgedeckt: `FUN_007f9b54`, `FUN_007fb450` und `FUN_007f7b0c` (Kollisionskomponente) laufen ebenfalls
  nur über die lokalen Spieler. Falls die Terrain-Höhen trotz Höhle 1 fern vom Host grob bleiben, dort weitersuchen.

**Test 4 (2026-10-27, Patch 0.3, Ambush auf `MN_Craters01_BG02_AmbA`).** Das Log zeigt alle 67 Einträge angewendet
und beide Höhlen angelegt (`Allocated 0x10000 for code at 0x1e90000 (entry=0x820088)`, `0x1ea0000 (entry=0x99ae94)`).
Im Speicherabbild sieht man nur die Höhlen-Befehle. Hook und `jumpl` stehen dort weiter als Original bzw. `nop`, weil
RPCS3 sie als „far jumps“ im Emulator führt und nicht in den Gastspeicher schreibt. Host 27 FPS, 4,3 GB.
- **Höhle 2 wirkt.** Der Host blendet genau die drei Proxies aus, die Client 2 ausblendet (`CS_GA_PowCore01S_LOD0_15`,
  `UC_GA_LandingP01M_LOD0_14`, `UC_GA_Reactor01M_LOD0_12`). Die übrigen 51 Proxies kollidieren. In `UC_GA_Reactor01M_12`
  kollidieren auf dem Host alle 4 StaticMeshActors (Patch 0.2: keiner). Insgesamt kollidieren 55 von 92 Actors der
  vollen Ebenen.
- **Höhle 1 reicht nicht.** Client 2 fiel an einer Stelle 1–2 m unter die sichtbare Geometrie (153686, 41792).
  `pawn_state.py`: auf dem Host `PHYS_Walking` auf `MegaTerrain_0` bei z 66259, beim Client `PHYS_Falling` ohne Base
  bei z 66184. Der Host hat dort nur grobe Kollisionskacheln (62 Kacheln, an der Stelle 32768 groß), der Client 207
  Kacheln, an der Stelle 2048 groß. `FUN_0081ffb4`/`FUN_00815548` steuern also nicht die Feinheit der Kollision.
- Die Kollisionskacheln verfeinert `FUN_007f9b54` (Komponente, Ereignis `0x2f`): Pro lokalem Spieler mit Pawn ruft
  sie `FUN_008240e8(komp, &Pawn.Location, komp+0x1f4, &3, 0)` auf, danach `FUN_00822d50(komp)`.
  **Patch 0.4:** Höhle 3 bei `0x7f9bf8` (Ende der Spielerschleife, `r29`/`r30` frei, `r31` = Komponente) ruft
  `FUN_008240e8` zusätzlich für jeden Pawn der PawnList auf. Höhle 1 bleibt drin. Eingetragen in Repo und Host,
  Sicherung des Hosts mit 0.3: `NPUB30643_patch.yml.before_lod04`. Wirksam erst nach einem Neustart des Hosts.

**Test 5 (2026-10-27, Patch 0.4, gleiche Karte).** Das Log zeigt alle drei Höhlen angelegt und 96 Einträge
angewendet, ohne Absturz. Client 2 fiel an derselben Stelle wieder durch (Client `PHYS_Falling` bei z 65522, Host
`PHYS_Walking` auf `MegaTerrain_0` bei z 66253). Der Host hat 93 Kacheln, die feinsten (8192) liegen bei (12800,
−16000), vermutlich an seiner Kamera. Am Client hat er weiter 32768er Kacheln, der Client 2048er. Höhle 3 in
`FUN_007f9b54` wirkt also nicht. Die Funktion läuft nur bei Ereignis `0x2f`.
- Die Verfeinerung pro Tick macht `FUN_007fb450`. Sie geht über die lokalen Spieler und nimmt die Pawn-Position oder,
  ohne Pawn, `LocalPlayer+0x94`. Liegen Kamera und Pawn mehr als 1000 Einheiten auseinander, ruft sie
  `FUN_008240e8` mit Typ 1 (Kamera) und Typ 2 (Pawn) auf, sonst einmal mit Typ 3. Im Dedicated-Pfad gibt es nur einen
  festen Punkt `0x1d39240` mit Typ 2. Danach bauen `FUN_00822b54`/`FUN_00822a48` die Kacheln neu.
- **Patch 0.5:** Höhle 3 sitzt jetzt bei `0x7fb7bc` (`ori r3,r29,0` vor `FUN_00822b54`, Normal- und Dedicated-Pfad
  laufen dort zusammen, `r29` = Komponente). Sie hat einen eigenen Stackrahmen und ruft
  `FUN_008240e8(komp, &Pawn.Location, komp+0x1f4, &3, 0)` für jeden Pawn der PawnList auf. Eingetragen in Repo und
  Host, Sicherung des Hosts mit 0.4: `NPUB30643_patch.yml.before_lod05`.

**Test 6 (2026-10-27, Patch 0.5, gleiche Karte): Terrain-Kollision passt.** Alle drei Höhlen laufen, ohne Absturz
(Host 26 FPS, 4,6 GB). Die unsichtbare Wand aus Test 3–5 ist weg. Die genaue Fallstelle von Test 4/5 hat der Tester
nicht mehr erreicht. Abbilder beider Instanzen mit Client 2 bei (126938, 37017):
- Pawn auf beiden Seiten `PHYS_Walking`, Höhe 66778.0 (Client) bzw. 66778.4 (Host), Position bis auf 0,3 Einheiten
  gleich.
- Der Host hat jetzt dieselben Kollisionskacheln wie der Client: 205 bzw. 207 Kacheln mit derselben Größenverteilung
  (40× 2048, 33× 4096, …), feine Kacheln im selben Bereich x 111104–169472, y 20480–53248. Die Kacheln unter dem
  Spieler sind auf beiden Seiten identisch (Mitte, Größe, Höhe).
- Damit ist Variante (a) umgesetzt. Patch 0.5 hat drei Höhlen: `0x820088` (Terrain-Streaming, für die Kollision
  wirkungslos, kann bleiben), `0x99ae94` (Überblendung, Test 4) und `0x7fb7bc` (Kollisionskacheln). Die zweite Zeile
  von Patch 0.2 ist entfallen.
- Offen: die Fallstelle (153509, 41800) gezielt nachprüfen, mehr als zwei Spieler, Speicher und FPS bei voller
  Belegung.

Hilfsmittel für diese Analyse in `research/tools_local/`: `live_dump.py` (Abbild aus dem laufenden Prozess, auch mit
`--no-gui`), `streaming_levels.py` (Streaming-Zustand), `pawn_state.py` (Spielerfiguren: Position, Physik, Base), `uobjects.py` (UObjects nach Klasse; Layout `+0x28` Outer,
`+0x2c` Name, `+0x34` Class). `tools/start_dust.ps1` gibt dem Spielfenster Titelleiste und Rahmen und hat `-OffsetX`.

### Parallel: EBOOT-Analyse mit Ghidra (in Absprache)

Gezielte Fragen an die entschlüsselte EBOOT:
- Was macht das Exec-Kommando `CleanLoad` (Strings `CleanLoad`, `credential`, `LightingMode`)?
- Gibt es `InitListen` / `?listen` im TcpNetDriver und einen Dedicated-Pfad (`GIsClient = FALSE`,
  `server`-Commandlet, `launchconfig`, `mDedicatedServerFlowIndex`)?
- Welche Python-Callbacks ruft der Server-Login auf (`GetDustCharacterURIFromCredential`,
  `OfflineLogin`, `OfflineConnect`, `BattleServerLogin`)?
- Ist der Cheat-Manager in der Release-Version aktiv (`CreateGame`, Spawn von KI-Spielern)?

## Anhang: Fundstellen

- `dust/battleClient3.py`: `Reload` 78, `JoinQueue` 231, `JoinBattle` 301, `OnBattleMemberJoinedFromBackend` 328,
  `OnBattleMemberConnectFromBackend` 344, `UpdateBattle` 356, `-autologinbattle` 373
- `dust/dustClient.py`: `InvokeSvcMethodOnBattleServerAsync` 158, `OnBattleMemberConnectNotification` 244
- `dust/dustUnreal.py`: `Start loginscene…` 41, `OnProceedBattleConnectNotification`/`CleanLoad` 69–70
- `dust/battleServer.py`: `OnDustUserLogonNotification` 163, `_LoginToBackend` 204, `_CompleteBattle` 223,
  `_MemberJoinedBattle` 287, `_ParseConfig` 354, `GetDustCharacterURIFromCredential` 409,
  `OnInvokeSvcMethodFromClient` 487
- `dust/app.py`: `CalculateRoleMask` 273/280, `CalculatePaths` 300; `dust/const.py`: `APP_ROLE_BATTLESERVER` 10
- `dust/startmini.py`: `GetBattleServices` 50, `InitApp` 251
- `dust/userClient.py`: `OfflineConnect` 238, `_HackOfflineBattleData` 288, `_InitBattleServices` 293
- `dust/userBattle.py`: `NUM_OFFLINE_PLAYERS` 13, `OfflineConnect` 32
- `dust/login.py`: `-autologinserver` 12, `OfflineLogin` 99, `_UserLoginWithPassword` 240
- `dust/characterConnectionClient.py`: `_NotificationCallback` 144
- `dust/ui/services/uiSvcBattle.py`: `OnSelect` 78, `JoinBattle` 128
- `dust/pingClient.py`: `_GetRegionsAndPing` 101
- `offline/offlineResourceMisc.py`: `OfflineBattleServerRegion` 141, `OfflineBattles` 180
- INIs (514_CROP-DUSTInG, 0319): `PS3-DustEngine.ini` (`[URL] Port=7777`, `[IpDrv.TcpNetDriver]`),
  `PS3-DustGame.ini` (`DefaultServerGame`, `DustGameSession`, `DustCheatManager`, `DustAIProfileMgr`),
  `DustEngine-DedicatedServerCook.ini` (`Client=WinDrv.WindowsClient`)
