# Charaktere, Skills und Skill-Training vom Server – Umsetzungsplan

Stand 2026-10-30. **Stufe 1 (1a, 1b) und Stufe 2 sind im Code umgesetzt**, hinter dem Schalter `DUST_CHAR_STORE=1`
(standardmäßig aus). Beide sind im Prozess getestet, in RPCS3 noch nicht (Funde und Testhinweise in `NOTES.md`). Die Stufen 2b
und 3 bis 5 sind offen. Außerdem ist
der AUR-Store bereinigt (Loyalty-Items standardmäßig aus). Das Dokument beschreibt Ziel, Reihenfolge und offene Entscheidungen.

Zur AUR-Wirtschaft (Quellen, Limits, Store-Bewertung, Euro-Einordnung) siehe `docs/aur_economy.md`. Sie wird erst ab Stufe 5 gebraucht.

## Ausgangslage

| Was | Heute | Quelle |
|---|---|---|
| Charakterliste (`GET /users/N/mercenaries/`) | drei feste „Offline Character 1–3“ | CCPs `offlineResourceUserCharacter.py` über `catma_service` |
| Benutzer | jedes RPCN-Konto ist `USER_ID` 1000000720, Token `dust-local-access-token` | `crest_app.oauth_token` / `token_decode` |
| `/characters/N/…` | ID wird ignoriert, immer Daten von 2100001611 | CCP-Offline + unsere Korrekturen (`mercenary`, `mercenary_private` …) |
| Skills (`GET …/mercenary/skills/`) | alle 221 Skills auf Stufe 5 | `offlineResourceSkill.py` |
| Skill kaufen/upgraden (`POST`/`PUT`) | No-op, nichts gespeichert | `offlineResourceSkill.py` |
| Charaktererstellung | Root-Links `bloodlines`, `dustSpecialties`, `dustPortraits` fehlen → vermutlich Trennung | – |
| Fittings | CCPs Liste im Speicher des `catma_service`, für alle Konten gemeinsam, nach Neustart weg | `offlineResourceFittings.py` |
| Wallet | eine globale `content/wallet.json` | `crest_app.account` |
| Gefecht (Host) | alle IDs 2100001611–2100001710: alle Skills Stufe 5, 999 von jedem Item, Fitting 100 | `userBattle.OfflineConnect` |

### Was die Recherche geklärt hat

- **Konto erkennbar:** Das `psn_ticket` im OAuth-Login (Ticket-Format 2.1, 256 Byte) enthält den RPCN-Namen im Klartext
  (z. B. `FinstererFred`) und die Dienst-ID `UP5018-NPUB30643`. Der Client schickt danach bei jeder Anfrage
  `Authorization: Bearer <token>` – ein Token pro Konto reicht, um jede Anfrage einem Benutzer zuzuordnen.
- **Startwerte stehen in CATMA** (Klasse `CharacterSpecialty`, je Rasse ein „Enforcer“):

  | typeID | Rasse | Start-SP | SP/Tag | Start-ISK |
  |---|---|---|---|---|
  | 353915 | Amarr | 500 000 | 24 000 | 25 000 |
  | 354241 | Caldari | 500 000 | 24 000 | 25 000 |
  | 354244 | Gallente | 500 000 | 24 000 | 25 000 |
  | 354247 | Minmatar | 500 000 | 24 000 | 25 000 |

  Dazu `startingSkills` (8 Einträge `skillTypeID`/`skillLevel`, z. B. 353352 L1 … 364519 L2) und `startingInventory`
  (rund 24 Einträge `type`/`quantity`/`shouldGiveFitting`/`shouldMakeFittingDefault`, also Starter-Fittings).
  Laut CATMA-Doku sind die Kosten der Start-Skills in den Start-SP enthalten.
  Namen/Beschreibungen sind `LocalizedString` und brauchen den Lokalisierungsdienst (außerhalb des Spiels nicht da).
- **Skill-Kosten:** `dust.skill.SKILL_COST_TABLE = [6220, 18650, 43530, 87060, 155460]` × `costMultiplier` des Skills;
  `GetSkillLevelCumulativeCost`, `MissingSkillsForType`, `GetRequiredSkillList` liegen im Client-Code und laufen im
  `catma_service`.
- **Freie SP rechnet der Client selbst:** `skillPoints` (aus der Charakterliste) minus kumulierte Kosten aller
  bekannten Skills. Der Server speichert also nur Gesamt-SP und Skill-Stufen.
- **Passiver Zuwachs:** Der Client zählt lokal alle `86400 / skillPointsPerDay` Sekunden +1 SP hoch, meldet aber
  nichts. Der Server muss die Gesamt-SP aus der Zeit berechnen. Passive SP gibt es pro Charakter nur, wenn
  `passiveSkillGain.status` 1 ist; die Auswahl hat dafür nur einen „Aktivieren“-Knopf
  (`characterCreation2.ActivateSkillGainCallback`, `PUT {status: 1}`), also vermutlich ein aktiver Charakter pro Konto.
- **Token-Erneuerung:** Der Token gilt laut unserer Antwort 3600 s; danach meldet sich der Client mit
  `grant_type=refresh_token` ohne Ticket an (`crest/authentication.py`). Der Refresh-Token muss also ebenfalls auf
  den Benutzer zeigen.
- **Löschen:** Die Auswahl liest `deletePrepareDate` (ISO-Datum) aus der Charakterliste: fehlt es, ist der Charakter
  normal; liegt es in der Zukunft, läuft der Countdown; liegt es in der Vergangenheit, kann endgültig gelöscht werden.
- **Gefecht:** `battleServer._MemberJoinedBattle` würde Skills über `mercenary['battleSkills']` laden und
  `OnPreCharacterConnectNotification` senden (`skillBattle`, `inventoryBattle` hören darauf). Im Listen-Server-Modus
  ist die `userBattle`-Session des Hosts nicht mit CREST verbunden; einfacher ist es, die Skills direkt in
  `/dev/battle/members/` mitzuschicken.
- **Icons:** Blutlinien `icon_bloodline_<name>` (amarr, ni-kunni, khanid, deteis, civire, achura, gallente, intaki,
  jin-mei, sebiestor, brutor, vherokior), Spezialisierung `icon_speciality_enforcer`, Porträts `id` 0–3 je Geschlecht.
  Blutlinie → Rasse (`dust.character.GetRaceIDFromBloodlineID`): 1, 2, 11 Caldari · 3, 4, 14 Minmatar ·
  5, 6, 13 Amarr · 7, 8, 12 Gallente.

## Grundsatzentscheidungen

1. **Speicher:** SQLite aus der Standardbibliothek, `dust_server/state/dust.sqlite` (überschreibbar mit
   `DUST_STATE_DIR`). `dust_server/` ist im Docker-Container beschreibbar eingebunden, der Stand überlebt also
   Neustarts. Zugriff nur über ein neues Modul `dust_server/store.py` (eine Verbindung, ein Lock), damit
   `crest_app.py` und `admin.py` keine SQL-Details kennen. Tabelle `meta(schema_version)` mit einfachen
   Migrationen beim Start; vor einer Migration eine Kopie `dust.sqlite.bak-<version>` anlegen.
2. **Spiellogik in Python 3:** Der `catma_service` liefert nur Stammdaten (neuer Endpunkt `GET /skills` und
   `GET /specialties`, einmal gebaut wie `/catalog`). Prüfungen (Voraussetzungen, Kosten) laufen in
   `dust_server/skills.py`. So bleibt die Python-2.7-Seite schlank.
3. **IDs:** Benutzer ab 1000001000, Charaktere ab 2100100000 – außerhalb der CCP-Offline-IDs
   (2100001611–2100001710), damit Reste aus CCP-Daten sofort auffallen. Gefechts-IDs bleiben bis Stufe 4 im
   Offline-Bereich (Host 2100001611 aus `dev_commands.json`, Spieler `first_member_id + n`), weil der Host nur für
   diese IDs Skills, Inventar und Fitting vorbereitet hat. Dass die CREST-ID des Hosts dann nicht mehr seiner
   Gefechts-ID entspricht, ist für Client 2 heute schon so und funktioniert – für den Host selbst muss es in Stufe 1
   getestet werden.
4. **CCP-Antworten als Vorlage:** Für Ressourcen mit vielen Links (Charakter, Mercenary, Private) bauen wir die
   Antwort selbst; für die übrigen pro Charakter (`mail`, `chat/channels`, `quests`, `contacts` …) nehmen wir CCPs
   Antwort und ersetzen 2100001611/1000000720 durch die echten IDs (eine Hilfsfunktion `rebind(result, user, char)`).
5. **Unbekannte Charakter-ID oder fremder Charakter:** 404 mit Log-Eintrag `missing:character`, kein Rückfall auf
   CCP-Daten (sonst sieht man Fehler nicht).

### Datenmodell (Stufen 1–3; Stufe 5 ergänzt Tabellen)

```
meta        (schema_version)
users       (id PK, online_id UNIQUE, created_at)
tokens      (token PK, refresh_token UNIQUE, user_id, expires_at)
characters  (id PK, user_id, name, gender, bloodline_id, race_id, specialty_id, portrait_id,
             corporation_id, sp_base, sp_per_day, sp_since, passive_sp, isk, npe_state, aur_spent,
             delete_ready_at, deleted, created_at)
skills      (character_id, type_id, level, PRIMARY KEY (character_id, type_id))
```

`sp_base` = SP zum Zeitpunkt `sp_since`; Gesamt-SP = `sp_base + passive_sp × sp_per_day × (jetzt − sp_since) / 86400`
(abgerundet). Bei jeder Änderung (Status umschalten, Belohnung) wird zuerst auf „jetzt“ umgerechnet
(`sp_base` neu, `sp_since = jetzt`). Namen sind nur unter nicht gelöschten Charakteren eindeutig – das prüft der Code,
kein `UNIQUE` in der Tabelle.

## Stufe 1 – Konten und Charaktere pro Konto

Ziel: Jedes RPCN-Konto hat eigene, gespeicherte Charaktere; alle Endpunkte pro Charakter antworten nach ID.
Die Stufe ist groß und wird in zwei Commits geteilt: **1a** Konten, Speicher, Charakterliste und die vier
Kerndokumente (Punkte 1–6, 8); **1b** Template-Ersatz für die übrigen Endpunkte und ISK pro Charakter (Punkt 7).

1. **Ticket lesen** (`dust_server/np_ticket.py`): Online-ID aus dem `psn_ticket` (Feld „online_id“ im
   Ticket-Body, 32 Byte, nullterminiert). Signatur vorerst nicht prüfen (lokaler RPCN-Server); als offener Punkt
   notieren. Test mit einem selbst gebauten Ticket (kein echtes aus den Logs ins Repo).
2. **`oauth_token`:** `grant_type=password`: Benutzer zur Online-ID suchen oder anlegen, eigenes Token und
   Refresh-Token (`secrets.token_hex`) ausgeben. `grant_type=refresh_token`: Benutzer über den Refresh-Token finden,
   neues Token ausgeben. Unbekannter Refresh-Token → 401 (der Client meldet sich dann neu an).
3. **`token_decode`** und eine Hilfsfunktion `current_user(req)` über den Bearer-Token. Geprüft wird nur bei
   Benutzer- und Charakter-Endpunkten; `/dev/…`, `/cdn/…`, Dokumente, Markt-Stammdaten und Notification-Streams
   bleiben ohne Token erreichbar (die Dev-Hook-Abfragen und der HTTP-Cache des Clients schicken keinen mit).
4. **Root-Daten (`dust_root`):** `user`- und `character`-Link auf den echten Benutzer bzw. ersten Charakter setzen.
   *Umsetzung: entfällt. Der Client holt `/roots/dust/` ohne Token, der Benutzer kommt über `/decode/`.*
5. **Spezialisierungen aus CATMA** (vorgezogen aus Stufe 2): `catma_service` bekommt `GET /specialties`
   (Rasse, Start-SP, SP/Tag, Start-ISK, Start-Skills, Start-Inventar), damit schon der automatische Startcharakter
   (Punkt 8) mit den richtigen Werten und Skills in der Datenbank landet. Ausgeliefert werden die Skills noch von
   CCP (alle Stufe 5), bis Stufe 2 umschaltet.
6. **Eigene Handler** (ersetzen CCP-Offline):
   - `GET /users/{id}/` (Links `mercenaries`, `notifications`)
   - `GET /users/{id}/mercenaries/` – MercenaryCollection-v1 mit den Feldern, die `characterCreation2` und
     `myCharactersClient` lesen: `character{id,name,href}`, `self`, `skillPoints`, `skillPointsPerDay`, `gender`,
     `bloodline{id,href}`, `portrait{id,href}`, `corporation{id,name,href,memberFor}`, `wealth{isk}`, `specialty`,
     `npeState`, `passiveSkillGain{status,self}`, `favoriteFitting`, `cycleCap`, `skillPointsThisCycle`
   - `GET /characters/{id}/`, `/characters/{id}/private/`, `/characters/{id}/mercenary/`,
     `/characters/{id}/mercenary/private/` (unsere heutigen Korrekturen wandern mit)
   - `PUT /characters/{id}/mercenary/` (`portraitID`, `aurSpent`, `npeState`) – jetzt wirklich speichern
   - `PUT …/passiveskillgain/{id}/` (Status speichern; aktiviert man einen Charakter, werden die anderen des
     Kontos deaktiviert – vorher prüfen, ob die Auswahl danach richtig aussieht)
7. **(1b)** Template-Ersatz (`rebind`) für `mail`, `chat/channels`, `contacts`, `quests`,
   `corporations/N/members/N/`, `inventory/N/owner/N/all/`, `mercenary/fittings/…`; ISK aus `characters.isk` statt
   `content/wallet.json` (`/accounts/{id}/…`, `wealth.isk` in der Liste). AUR bleibt pro Konto global in
   `wallet.json` bis Stufe 5; die Wallet-Seite im Web-Admin zeigt dann nur noch AUR, ISK wandert auf die
   Charakter-Seite (Stufe 2).
8. **Übergang:** Konten ohne Charaktere bekommen in Stufe 1 automatisch einen Startcharakter
   (Amarr-Enforcer, Name = Online-ID, `npeState` 1 wie CCPs Charakter 1), weil die Erstellung erst in Stufe 3 kommt.
   Der unbemannte Host (`-autologincharindex`) braucht ohnehin immer einen Charakter.
9. **Notification-Streams** sind schon pro Pfad (`/characters/{id}/notifications/`) – nichts zu tun, nur prüfen.
   Hinweis aus der Docker-Sitzung (2026-10-26, Commit 50150b3): Weil heute alle denselben Offline-Charakter haben,
   gehen `OnBattleMemberJoined`/`OnBattleMemberConnect` zusätzlich nur an Streams von der IP des Beitritts
   (`HUB.send(..., peer)`); sonst verbindet sich der Host selbst als Client und alle Spieler fliegen raus. Mit eigenen
   Charakter-IDs ist das überflüssig und kann stören (Beitritt und Stream über verschiedene Adressen, z. B.
   IPv4/IPv6 oder Proxy). Den Peer-Filter dann entfernen oder nur noch nutzen, wenn mehrere Streams denselben
   Besitzer haben. Wichtig: Kein echter Charakter darf eine ID aus dem Offline-Bereich bekommen (siehe
   Grundsatzentscheidung 3), sonst bekäme er wieder die Nachrichten des Hosts.

**Umsetzung 1a (2026-10-30):** `store.py`, `np_ticket.py`, `catma_service/specialties.py`, Handler in `crest_app.py`.
Schalter `DUST_CHAR_STORE=1`, Host-Konten über `DUST_HOST_ACCOUNTS` (Standard `DustHost`; sie und der alte Token bleiben auf
CCP-Offline). Unser eigener Charakterbereich (ab 2100100000) ist strikt: Eine unbekannte ID gibt 404, ebenso ein fremder
Charakter bei privaten Dokumenten. Öffentliche Dokumente sind für alle lesbar. Tests: `python -m unittest discover -s dust_server/tests`.
Dazu gehört `tools/legacy_parity.py`, ein Regressionstest. Er vergleicht ohne Schalter 26 Anfragen mit dem Stand vor 1a
(Commit e930d67) und braucht dafür den CATMA-Dienst; läuft der nicht, überspringt der Unit-Test ihn. Ändert sich das
Verhalten für die Offline-Charaktere absichtlich, wird die Baseline im Werkzeug angepasst.

**Umsetzung 1b (2026-10-30):** Statt einzelner Handler gibt es einen allgemeinen Rückfall in `CrestApp.dispatch`. Ein Pfad
mit eigener Charakter-ID geht an CCPs Handler mit 2100001611, danach wird `rebind` angewendet. Er gilt nur für den Besitzer,
weil sich öffentlich und privat dort nicht unterscheiden lassen. ISK pro Charakter in `/accounts/{id}/…`. Die Wallet-Seite im
Admin weist darauf hin; die Charakter-Seite folgt in Stufe 2.

**Prüfen:** Zwei RPCN-Konten (FinstererFred, DustTester2) loggen ein, sehen je einen eigenen Charakter mit eigenem
Namen; Neustart des Servers → Charaktere noch da; nach über einer Stunde im Spiel (Token-Erneuerung) weiterhin
verbunden und derselbe Benutzer; `requests.jsonl` zeigt für `/users/…` und `/characters/…` nur noch
`own:`-Quellen. Mehrspielertest (Host + Client 2) läuft weiter – vor allem der Spawn des Hosts mit neuer CREST-ID.

## Stufe 2 – Skills und Skill-Training

Ziel: Echte Skill-Stufen, Kaufen/Upgraden kostet SP, SP wachsen mit der Zeit.

1. **`catma_service`: `GET /skills`** – für jeden der 221 Skills `typeID`, interner Name, `costMultiplier`,
   Voraussetzungen (über `dust.skill.GetRequiredSkillList`; Format beim Umsetzen prüfen). `content.py` lädt das
   einmal (wie `catalog()` und `/specialties` aus Stufe 1).
2. **`dust_server/skills.py`:** `cumulative_cost(type_id, level)`, `free_sp(char)`, `can_buy(char, type_id)`,
   `can_upgrade(char, type_id, current, aim)`.
3. **Handler:**
   - `GET /characters/{id}/mercenary/skills/` – DustCharacterSkillCollection: `items` mit `skillTypeID`,
     `skillLevel`, `skillName`, `href` (`…/skills/{typeID}/`); `page=all` und `next` unterstützen (der Host fragt mit
     `page=all`).
   - `POST …/skills/` `{skillTypeID}` – Skillbuch: Stufe 1 anlegen, wenn Voraussetzungen erfüllt und genug freie SP.
   - `PUT …/skills/{typeID}/` `{skillTypeID, currentLevel, aimLevel}` – Upgrade mit Prüfung
     (`currentLevel` stimmt, `aimLevel ≤ 5`, SP reichen).
   - Link `battleSkills` im Mercenary-Dokument (für Stufe 4 und einen späteren echten Battle-Server).
4. **Fehlerfall:** Der Client prüft vorher selbst (UI zeigt nur machbare Upgrades). Ablehnungen sollten also nur bei
   Manipulation oder veralteten Daten vorkommen. Vor dem Umsetzen prüfen, wie `crest.errors` einen 400er behandelt
   (`DisconnectOnError`?); notfalls statt Fehler eine Benachrichtigung `OnCharacterSkillChangeFromBackend` mit dem
   echten Stand senden.
5. **SP-Zuwachs:** Gesamt-SP nach obiger Formel bei jeder Abfrage, nur für den Charakter mit aktivem
   `passiveSkillGain`; `skillPointsPerDay` aus der Spezialisierung (24 000). Ist kein Charakter aktiv, steht in der
   Liste `skillPointsPerDay` 0, damit der lokale Zähler des Clients nicht falsch hochzählt.
6. **Web-Admin, Seite „Characters“ (Grundversion):** Konten und Charaktere auflisten, SP und ISK setzen, Skills auf
   den Startstand zurücksetzen. Wird schon zum Testen des Trainings gebraucht; der Ausbau folgt in Stufe 5.
7. **Optional 2b:** `respec` (alle Skills zurücksetzen), Sammel-Upgrade
   `POST mercenaryProgressionCollections` (`MercenaryProgressionSkillUpgrade-v1`, `loadoutProgressionClient.py`),
   Skill-Booster (`boosters`).
   **Respec umgesetzt (2026-10-30):** nur über das Item 367499 „Skill Tree Reset and Refund“ (Assets → benutzen, oder nach dem
   Kauf im Markt). `PUT <mercenary respec>` setzt die Skills auf die Start-Skills zurück, Corp-Skills (Marktgruppe 363476)
   bleiben, gekaufte Skillbücher kommen zu 80 % des Marktpreises als ISK zurück. Das Item wird nicht verbraucht, solange das
   Inventar CCPs gemeinsame Liste ist (Stufe 5).

**Umsetzung (2026-10-30):** `catma_service/skilldata.py` (`GET /skills`), `dust_server/skills.py`, Handler in `crest_app.py`,
Admin-Seite „Characters“. Abweichungen vom Plan: `POST` legt Stufe **0** an (Skillbuch gelesen), nicht 1; Ablehnungen sind
200 mit Log-Eintrag statt 400 (der Client fängt keine Fehler ab). Punkt 5 (SP-Zuwachs) lag schon in `store.py`.

**Prüfen:** Neuer Charakter zeigt 8 Start-Skills und passende freie SP; Skill kaufen/upgraden → nach Neu-Login
weiterhin da, freie SP gesunken; nach einigen Minuten sind die Gesamt-SP des aktiven Charakters serverseitig
gestiegen, die der anderen nicht. Kleine Python-Tests für `skills.py` (Kosten, Voraussetzungen) und `store.py`
(SP-Formel, Umschalten) ohne laufendes Spiel.

## Stufe 3 – Charaktererstellung und Löschen

Ziel: Leere Plätze in der Auswahl funktionieren, bis zu drei Charaktere pro Konto.

1. **Root-Links** `bloodlines`, `dustSpecialties`, `dustPortraits` (der Client liest genau diese Namen) in `dust_root`.
2. **Stammdaten:**
   - `GET /bloodlines/` – 12 Einträge `{id, href, name, description, icon{href: icon_bloodline_…}, race{href}}`,
     Namen/Texte englisch fest im Code (EVE-Blutlinien).
   - `GET /specialties/` – 4 Einträge aus CATMA, `icon{href: icon_speciality_enforcer}`, `race{href}`;
     Name/Beschreibung fest („Enforcer“ + kurzer Text), da die Lokalisierung fehlt (optional später aus den
     Lokalisierungsdaten des Clients ziehen).
   - `GET /portraits/mercenary/` – 8 Einträge `{href, image{id 0–3, gender}}`.
   - `GET /races/` bleibt CCP-Offline (passt schon).
3. **`POST /users/{id}/mercenaries/`** (MercenaryItemCreate-v2 `{name, gender, bloodline}`): Name prüfen (Länge,
   Zeichen, eindeutig), max. 3 aktive Charaktere, Rasse aus der Blutlinie, Spezialisierung über die Rasse (wie
   `myCharactersClient.GetSpecialtyID`), Start-Skills/-SP/-ISK eintragen, NPC-Corp je Rasse, Porträt nach
   `GetPortraitIDByRace` (Caldari 0, Gallente 1, Amarr 2, Minmatar 3). Antwortformat und Fehler bei doppeltem
   Namen vor dem Umsetzen in `characterCreation2.py` nachlesen.
4. **Löschen:** `POST <self> {prepareDelete: true|false}` setzt `delete_ready_at = jetzt + Wartezeit` bzw. löscht es;
   die Liste gibt es als `deletePrepareDate` (ISO) aus. `DELETE <self>` löscht nur, wenn die Zeit erreicht ist
   (weich: `deleted = 1`). Wartezeit konfigurierbar, Standard 1 Minute (damit man den Countdown sieht).
5. Der automatische Startcharakter aus Stufe 1 wird abgeschaltet (Ausnahme: Host-Konto, siehe offene Fragen).
6. **Ersten Login testen:** Ein Konto ohne Charakter landet direkt in der Auswahl mit drei leeren Plätzen; prüfen,
   dass Root-Daten ohne `character`-Link den Client nicht stören.

**Umsetzung (2026-10-30):** Regeln in `dust_server/characters.py`, Handler in `crest_app.py`. Abweichungen: 10 statt 12
Blutlinien (Ni-Kunni und Jin-Mei haben im Client kein Icon). Fehler (Name vergeben/ungültig, kein freier Platz, Löschen zu
früh) gehen als 403 mit `title`/`message` zurück, das zeigt der Client als Popup. Wartezeit per `DUST_DELETE_WAIT` (Sekunden,
Standard 60). Kein automatischer Startcharakter mehr. NPC-Corp je Rasse (offene Frage 3).
`npeState` neuer Charaktere 1 wie CCPs Offline-Charakter, sonst würde vermutlich das Tutorial starten.

**Prüfen:** Leeren Platz wählen → Geschlecht, Rasse, Blutlinie, Spezialisierung → Name → Charakter erscheint mit
richtigen Icons, Start-Skills und ISK; Löschen und Abbrechen des Löschens; vierter Charakter nicht möglich.

## Stufe 4 – Echte Skills im Gefecht

Ziel: Im Listen-Server-Gefecht gelten die Skills des Spielers statt „alles Stufe 5“.

1. **`join_battle`:** Den CREST-Charakter des Beitretenden (`character.href` im Body) merken; in
   `register_listen_member` Name, Rasse, Corp, Geschlecht und die Skill-Liste mitgeben.
2. **`/dev/battle/members/`:** Jedes Mitglied bekommt `skills: [[typeID, level], …]`. Für den Host selbst liefert der
   Server einen Eintrag mit `"host": true` (heute steht der statisch in `dev_commands.json`). Welcher Charakter das
   ist, weiß der Server über das Host-Konto (offene Frage 1), nicht über die Dev-Abfrage, die keinen Token trägt.
3. **`client_patch/dustdevhook.py` `_BattleMember`:** `skillBattle.knownSkills[charID]` setzen und
   `skillBattle._UpdateDataCache(charID)` aufrufen (aktualisiert `_pystims`); für IDs außerhalb
   2100001611–2100001710 zusätzlich `inventoryBattle.characterCache` und `fittingBattle2.SetSpawnFitting` wie in
   `userBattle.OfflineConnect` füllen. Danach `COMMON.SDAT` neu patchen (`tools/patch_common_sdat.py`) – auf dem
   Host reicht es, die Spieler-Clients müssen nichts ändern.
4. **Gefechts-IDs:** Optional die echten Charakter-IDs statt `first_member_id + n` verwenden (der Host vergibt die
   ID über den Login-Credential-Zweig, deshalb ist das frei wählbar). Erst nach erfolgreichem Test mit den alten IDs.
   Hinweis: Die Werte im Fitting-Bildschirm des Clients rechnet `stimsFactory` mit der CREST-ID; im Gefecht zählen
   die Werte des Hosts. Unterschiedliche IDs sind also höchstens eine Anzeigefrage.
5. **Folge:** Der Host prüft beim Spawn Fitting gegen Skills – ein Fitting ohne passende Skills lässt sich dann nicht
   mehr spawnen. Das ist gewollt, muss aber zu den Fittings des Clients passen (siehe Stufe 5).

**Prüfen:** Client 2 mit einem Charakter ohne z. B. Schwere-Dropsuit-Skill → Fitting wird abgelehnt bzw.
Werte (Schild/Panzerung) entsprechen den Skills; `client.log` des Hosts zeigt „skills updated for character“.

## Stufe 5 – Später

- **Fittings pro Charakter speichern** (heute CCPs gemeinsame Liste im `catma_service`-Speicher):
  `GET/POST …/mercenary/fittings/`, `GET …/fittings/{id}/`, `PUT …/slots/{slot}/`; Starter-Fittings aus
  `startingInventory` (`shouldGiveFitting`, `shouldMakeFittingDefault`).
- **Inventar pro Charakter** (`inventory/{id}/owner/{id}/all/`) mit Start-Items; Käufe im ISK-Markt, AUR-Store und
  LP-Store buchen ISK/AUR/LP ab und legen Items an.
- **Gefechtsbelohnungen** (SP/ISK nach Matchende): Der Host meldet heute nichts; neuer Dev-Endpunkt, den
  `dustdevhook` am Matchende aufruft.
- **Login-Bonus** (`content/rewards.json`) wirklich gutschreiben, wenn `characterRewardReceived` gesetzt wird
  (Ablauf in `welcomeScreen.py` nachlesen; vorher aus Stufe 2 hierher verschoben).
- **Web-Admin:** Seite „Characters“ aus Stufe 2 ausbauen – einzelne Skills, Inventar und Fittings ändern,
  Charakter löschen; AUR pro Konto statt global.
- **AUR-Wirtschaft** (eigene Datei `docs/aur_economy.md`): AUR im Spiel verdienen statt kaufen.

## Offene Fragen und Entscheidungen

1. **Host-Konto:** Der unbemannte Host braucht immer einen Charakter. Vorschlag: Konto aus `DUST_HOST_ACCOUNT`
   (Online-ID) bekommt automatisch einen Charakter „Battle Host“, der in der Gefechtsliste nicht mitzählt.
   **Entscheidung des Nutzers (2026-10-26):** Der Host bleibt bei einem CCP-Offline-Charakter (2100001611), das ist
   am einfachsten. Folgen: Das Host-Konto muss weiter die Offline-Charaktere sehen, sonst findet
   `-autologincharindex=0` keinen Charakter. Das Host-Konto ist im Docker-Stack `DustHost` am eigenen RPCN
   (`docker/rpcn`); lokal kommen die Host-Anfragen von `127.0.0.1` (siehe `DUST_HOST_PEERS`). Ob das über ein festes
   Host-Konto oder den bisherigen Offline-Pfad läuft, entscheidet die Umsetzung. Der automatische Startcharakter
   (Stufe 1, Punkt 8) gilt für dieses Konto nicht.
2. **Bestehende Testaufbauten:** Beide Test-RPCN-Konten starten in Stufe 1 mit einem frischen Charakter
   (die alten Offline-Charaktere verschwinden). Alternative: einmaliger Import von „Offline Character 1–3“ für das
   erste Konto.
3. **Minmatar-NPC-Corp (gelöst 2026-10-30):** CATMA `starting_corporations_global` listet 12 Start-Corps je Rasse, die Namen
   kommen aus der öffentlichen ESI (`dust_server/characters.py`). Neue Charaktere: Amarr 1000205, Caldari 1000214, Gallente 1000216
   (die Corps der Offline-Charaktere), Minmatar 1000251 Brutor Vanguard (erster Listeneintrag). Wie CCPs Backend wählte, ist offen.
4. **Startstation:** Heute Ana (Amarr) für alle; pro Rasse eigene Station wäre korrekter, braucht aber
   `/locations/`- und `/stations/`-Daten pro Rasse.
5. **Ticket-Signatur:** Für einen öffentlichen Server sollte das RPCN-Ticket gegen den Schlüssel des RPCN-Servers
   geprüft werden, sonst kann sich jeder als beliebiges Konto ausgeben.
6. **SP-Obergrenze:** DUST hatte eine wöchentliche Obergrenze für Gefechts-SP (`cycleCap`); erst mit Stufe 5 relevant.
7. **AUR-Store-Angebot:** Bewertung, Einstellungen und Entscheidungen stehen in `docs/aur_economy.md`. Offen sind nur noch die
   genauen AUR-Werte pro Match und für die Login-Belohnung.

## Ergänzungen nach dem Gegenlesen (2026-10-29, Vorschläge, noch nicht entschieden)

1. **Zugriffsschutz:** `/dev/*` und Notification-Streams sind laut Plan ohne Token erreichbar. Auf einem lokalen Setup ist das
   egal, auf einem von außen erreichbaren Server nicht. `GET /dev/battle/members/` enthält die Credentials der Mitspieler (damit
   könnte sich jemand im Gefecht als anderer Spieler ausgeben), und Streams mit fortlaufender Charakter-ID im Pfad könnten fremde
   `OnBattleMemberConnect`-Nachrichten mitlesen. Vorschlag: `/dev/*` auf `DUST_HOST_PEERS` oder ein Shared Secret beschränken und
   prüfen, ob sich Streams an eine Sitzung binden lassen. Die Ticket-Signaturprüfung (Offene Frage 5) gehört in dieselbe Kategorie.
2. **Stufe 4 und Stufe 5 hängen zusammen:** Der Host entscheidet beim Spawn über das Fitting und braucht dafür Fittings und Inventar
   des Spielers, nicht nur die Skills. Solange Fittings eine gemeinsame Liste sind und der Host 999 von jedem Item annimmt, wirken
   Skills allein nur halb. Entweder ein minimales Fitting-Speichern pro Charakter vorziehen, oder festhalten, dass Stufe 4 bis
   dahin nur Skill-Werte, aber keine Ausrüstungsprüfung liefert.
3. **Zuordnung Gefechts-ID → Charakter:** Bis Stufe 4 bleiben die Gefechts-IDs im Offline-Bereich (`first_member_id + n`) und hängen
   von der Beitrittsreihenfolge ab. Für Belohnungen und Statistiken pro Gefecht in der Datenbank speichern, welcher CREST-Charakter
   welche Gefechts-ID bekam (der Server kennt das beim Beitritt schon).
4. **Strikt/lax (Grundsatzentscheidung 5):** Ein 404 statt CCP-Rückfall ist gut für die Fehlersuche, kann aber den Client trennen,
   je nachdem, wie `crest.errors` Fehler behandelt. Einen Schalter einbauen (strikt im Test, lax im Betrieb) und früh prüfen, wie der
   Client auf 404 und 400 reagiert.
5. **SQLite im Docker:** WAL-Modus einschalten. Liegt `dust_server/state/` auf einem Windows-Bind-Mount, besser ein Docker-Volume
   verwenden (Dateisperren). Regelmäßig `dust.sqlite` sichern. Käufe und Upgrades in einer Transaktion ausführen (Prüfung und
   Abbuchung zusammen), damit Doppelklicks nichts doppelt abbuchen.
6. **Host-Ausnahme ausdrücklich:** Das Host-Konto (Offline-Charakter 2100001611) ist eine Ausnahme von „kein Rückfall auf CCP-Daten“.
   Diese Ausnahme im Code benennen (Host-Konto per Konfiguration), statt sie als stillen Fallback zu lassen.
7. **Reihenfolge:** Die Skalierungsmessung des Hosts (siehe `CLAUDE.md`) vor Stufe 1 machen, weil sie die Ausrichtung des
   Gesamtprojekts beeinflussen kann.

## Reihenfolge und Aufwand (grob)

| Stufe | Inhalt | Dateien | Aufwand |
|---|---|---|---|
| 1a | Konten, Token, Speicher, Charakterliste, Kerndokumente, Startcharakter | `store.py`, `np_ticket.py`, `crest_app.py`, `catma_service/offline_service.py`, `content.py` | groß |
| 1b | Template-Ersatz, ISK pro Charakter | `crest_app.py`, `admin.py` (Wallet) | mittel |
| 2 | Skills, Training, SP-Zuwachs, Admin-Seite (Grundversion) | `catma_service/offline_service.py`, `skills.py`, `content.py`, `crest_app.py`, `admin.py`, `admin_ui/` | mittel |
| 3 | Erstellung, Löschen, Stammdaten | `crest_app.py`, `store.py` | mittel |
| 4 | Skills im Gefecht | `crest_app.py`, `client_patch/dustdevhook.py` | klein–mittel |
| 5 | Fittings, Inventar, Käufe, Belohnungen, Admin | mehrere | groß |
| 5+ | AUR-Wirtschaft (`docs/aur_economy.md`: Quellen, Limits, Journal, Store-Anpassungen) | `store.py`, `crest_app.py`, `content.py`, `admin.py` | mittel |

Jede Stufe endet mit einem Test in RPCS3 (Host + Client 2) und einem Commit; README und `docs/setup_guide_en.md`
werden pro Stufe nachgezogen.
