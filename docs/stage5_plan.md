# Stufe 5, Restplan (Stand 2026-10-30)

Stufe 5a (Inventar, Fittings, Käufe pro Charakter) ist fertig, siehe `character_server_plan.md`. Hier der Rest in kleinen
Schritten. Jeder Schritt läuft hinter `DUST_CHAR_STORE`, wird zuerst im Prozess (Wegwerf-DB) und dann in RPCS3 geprüft
und einzeln committet. Die Parität ohne Schalter (`tools/legacy_parity.py`) muss jedes Mal gleich bleiben.

## 5a-Rest: in RPCS3 bestätigen (klein)

- LP-Kauf: im Web-Admin ein LP-Angebot und ein Guthaben setzen, kaufen, Guthaben und Assets prüfen.
- Skillbuch lesen und Respec: Das Item verschwindet aus den Assets, ohne Item wird abgelehnt.

## 5b: Matchende und Belohnungen (mittel, zuerst)

Der Client-Code hat CCPs Ablauf schon: `battleServer.OnBattleServerStoppedFromUnreal` → `_CompleteBattle` holt
`MatchInfo.GetEndOfMatchPlayerInfoList()` (Warpoints je `characteruri`) und je Spieler `consumed`/`nonConsumed` aus
`inventoryBattle`, dann `POST battle.completed` (`BattleServerBattleCompleted-v1`: `winningTeam`, `members[team, character,
duration, warpoints, consumed, nonConsumed]`, Clone-Verluste). Wer früher geht, bekommt `POST member.completed`.

1. **Prüfen:** Ruft der Listen-Host am Matchende `OnBattleServerStoppedFromUnreal` auf, und ist `self.battle`/`self.config`
   dort gesetzt? Log-Zeile im Dev-Hook, ein Ambush zu Ende spielen.
2. **Dev-Hook:** `_CompleteBattle` bzw. `_MemberLeftBattle` so patchen, dass sie an `POST /dev/battle/completed/` und
   `/dev/battle/members/{id}/completed/` schicken (nur vom Host, `from_host`). Gleiche Nutzdaten wie bei CCP.
3. **Server: Gefechts-ID → Charakter** speichern (Ergänzung 3 im Hauptplan). `register_listen_member` kennt beides schon,
   die IDs laufen aber um. Also pro Gefecht eine Tabelle `battle_members(battle, battle_char_id, character_id, team)`.
4. **Belohnung buchen** (eine Transaktion pro Gefecht): SP und ISK aus Warpoints und Sieg/Niederlage. Formel in
   `content/rewards.json` (Web-Admin), Startwerte nach `docs/aur_economy.md`. Wöchentliche SP-Obergrenze (`cycleCap`,
   `skillPointsThisCycle`) erst einmal fest, z. B. aus CATMA, falls vorhanden, sonst aus `rewards.json`.
5. **Verluste abbuchen:** `consumed` vom Inventar abziehen, aber nie unter 0 (der Host rechnete mit 999). Optional erst
   nur loggen und vergleichen, ob die Mengen stimmen.
6. **Client informieren:** `OnCharacterSkillPointChange`, `OnAccountUpdated`, `OnItemsChanged`. Prüfen, was der Client nach
   dem Match anzeigt (Ergebnisbildschirm/Battle-Report, eventuell eigenes Dokument). Rückkehr in die Merc Quarters
   ist `CLAUDE.md` Schritt 5 und gehört dazu.

**Stand 2026-10-30:** Punkte 2–6 umgesetzt und im Prozess geprüft (Details in `NOTES.md`), Punkt 1 und die
Abnahme in RPCS3 stehen aus. Verluste zählt der Dev-Hook über `fittingBattle2.DestroyFitting`, weil der Host kein
Inventar führt.

Fertig, wenn: Nach einem Ambush in RPCS3 hat der Charakter mehr SP und ISK, verbrauchte Granaten/Nanohives fehlen im Inventar,
das Log zeigt die Buchung pro Spieler.

## 5c: Inventar im Gefecht (klein, nach 5b)

Der Host legt Inventar nur für Offline-IDs an (`inventoryBattle`, 999 von allem, `FAKE_INVENTORY_QUANTITY`). Wie bei den
Skills (Stufe 4) beim Beitritt das echte Inventar mitschicken (`/dev/battle/members/`) und im Dev-Hook
`inventoryBattle.characterCache[ID]` damit füllen. Folge: Ein Fitting, dessen Teile fehlen, lässt sich nicht spawnen.
Erst nach 5b, sonst verliert man Ausrüstung, ohne sie abzubuchen, oder hat sie doppelt.

## 5d: Login-Bonus (klein)

`dailybonusinfo` liefert heute immer `consecutiveLogons: 1`, `characterRewardReceived: False`. Neu: pro Charakter/Konto
den letzten Bonus-Tag und die Serie speichern. Beim ersten Login des Tages SP (Charakter) und AUR (Konto) aus
`rewards.json` gutschreiben und einmal `…RewardReceived: False` melden (der Willkommensbildschirm animiert dann), danach
`True`. Ablauf und Felder in `welcomeScreen.py` (Zeilen 700–750) und `questsClient.py` nachlesen.

## 5e: Inventar-Aktionen (klein bis mittel)

`POST inventory/{id}/owner/{id}/all/`, unterschieden am Content-Type:
- `InventoryItemUse-v1`: Booster aktivieren (`boosterClient`, eigener Endpunkt prüfen) und Salvage-Boxen. Erst die
  Item-Arten listen, die der Client benutzbar macht.
- `InventoryItemSellToNpc-v1`: **Entscheidung nötig**, wie viel ISK es gibt (Vorschlag: 50 % des Marktpreises).
- `InventoryItemGiveToAnotherCharacter-v1`: zwischen eigenen Charakteren bzw. Spielern, mit `OnItemsChanged` an beide.

## 5f: Web-Admin (klein bis mittel)

Seite „Characters“: Inventar ansehen und ändern (Item hinzufügen per Name, Menge setzen), Fittings ansehen/löschen,
AUR pro Konto und LP pro Charakter setzen, Charakter löschen. Änderungen per Benachrichtigung live an den Client
(wie bei Skills). Die Wallet-Seite erklärt, dass ihre AUR-/LP-Werte nur noch Startwerte sind.

## Reihenfolge

5a-Rest → 5b → 5c → 5d → 5f → 5e. 5b schließt den Kreislauf (Gefecht → SP/ISK → kaufen → Fitting) und ist Voraussetzung
für 5c. 5f hilft beim Testen aller späteren Schritte und kann vorgezogen werden.
