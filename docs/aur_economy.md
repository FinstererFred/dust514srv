# AUR-Wirtschaft ohne Echtgeld (aus dem Charakter-Plan ausgelagert)

Stand 2026-10-29. Ausgelagert aus `character_server_plan.md`, damit der Plan für Stufe 1 bis 4 kurz bleibt.
Diese Datei wird erst ab Stufe 5 gebraucht (AUR pro Konto, Käufe im AUR-Store, Gefechtsbelohnungen).

Ziel: Spieler kommen ohne Echtgeld an AUR, aber das System lässt sich nicht ausnutzen. AUR wird wie jede andere
Ingame-Währung behandelt: man verdient sie im Spiel, langsamer als ISK und mit Obergrenzen. Baut auf Stufe 5 auf
(AUR pro Konto, Käufe im AUR-Store, Gefechtsbelohnungen).

**Warum nicht einfach viel AUR für alle:** Unbegrenztes AUR schafft die Währung praktisch ab. Kosmetik und
gleichwertige AUR-Varianten wären harmlos. Problematisch sind aber zwei Gruppen:

- **Active Booster** mit mehr SP-Gewinn: Laufen sie dauerhaft, steigen alle schneller auf, und das SP-Tempo ist im
  Grunde neu festgelegt.
- **Alles, was dauerhaft Ausrüstung liefert** (BPO-artige Items): Verluste im Kampf kosten nichts mehr, der
  ISK-Kreislauf bricht zusammen.

Diese Items müssten bei „viel AUR für alle“ sowieso einzeln entschärft werden.

**Quellen für AUR:**

1. **Startguthaben pro Konto, nicht pro Charakter** (4 000–5 000 AUR, etwa ein 18-€-Paket), damit neue
   Charaktere kein Gratis-Geld bringen.
2. **Tägliche Login-Belohnung:** Das Feld `aur` in `content/rewards.json` gibt es schon (ausgeliefert über
   `crest_app.py`); fehlt nur die Gutschrift (Stufe 5, Login-Bonus) und sinnvolle Werte.
3. **AUR pro Match mit Wochenlimit:** kleine Summe pro abgeschlossenem Match, Bonus für den ersten Sieg des Tages,
   festes Maximum von etwa 1 000 AUR pro Woche (analog zu `cycleCap` für SP). Das Limit ist der wichtigste Schutz
   gegen Farmen.
4. **Einmalige Meilensteine**, z. B. bei SP-Grenzen oder der ersten Nutzung einer neuen Rolle.
5. **Optional: ISK in AUR umtauschen, nur in diese Richtung**, mit festem Kurs und Limit. Entzieht dem Spiel ISK
   (gegen Inflation) und gibt Vielspielern etwas zu tun, ohne dass es kippt. Kurs deutlich schlechter als CCPs
   Preisverhältnis (etwa 1 AUR = 2 500 ISK), sonst wird der Umtausch zum bequemsten Weg an AUR.

**Schutz gegen Ausnutzen:** DUST hat keinen Handel zwischen Spielern; Echtgeld-Handel und Verschieben zwischen
Konten fallen damit weitgehend weg. Bleiben:

- **Nur der Server bucht.** Der Client darf nie selbst AUR anfordern; jede Gutschrift entsteht serverseitig und wird
  mit Grund und Zeitstempel protokolliert (neue Tabelle, z. B. `aur_journal (user_id, amount, reason, ref, created_at)`),
  einsehbar im Web-Admin.
- **Match-Belohnung nur bei echter Teilnahme:** Mindest-Spielzeit, Mindest-War-Points und eine Mindestzahl echter
  Spieler im Match – gegen AFK-Farmen und leere Matches zu zweit.
- **Nur vertrauenswürdige Battle-Hosts:** Kommen später Community-Hosts dazu, nimmt der Hauptserver Match-Ergebnisse
  nur von freigegebenen Hosts an (z. B. Schlüssel pro Host). Sonst meldet ein eigener Host erfundene Ergebnisse.
- **Booster begrenzen:** Laufzeit pro Kauf, kein Stapeln, gegebenenfalls höherer Preis.

**Alternative für kleine, private Runden:** Statt viel AUR zu verteilen, im Store die Preise auf 0 setzen bzw. auf
ISK umstellen und die Booster entschärfen. Kommt aufs Gleiche heraus, ist aber ehrlicher und einfacher zu pflegen.

**Empfehlung:** Startguthaben pro Konto, Login-Belohnung und Match-Belohnung mit Wochenlimit, dazu Booster
einschränken und den AUR-Store wie unten bereinigen.

## Einordnung in Euro

Damals gab es 4 000 AUR für 18 €, also 1 AUR ≈ 0,45 Cent. CCPs Preise ergeben grob 1 AUR ≈ 1 000–1 500 ISK
(`'Pyrus' Assault Rifle` 4 AUR, normales Gewehr 4 020 ISK).

| Item | AUR | ca. € |
|---|---|---|
| Verbrauchbare AUR-Waffe oder -Anzug (Standard bis Prototype) | 3–13 | 1–6 Cent pro Stück |
| Active Booster (1 Tag) | 200 | 0,90 |
| Skin-BPO (z. B. `'Valor' Assault C-I`) | 1 280 | 5,75 |
| Militia-Fahrzeug-BPO (z. B. Gorgon) | 1 500 | 6,75 |
| Quafe-Skin | 3 480 | 15,70 |

Mit etwa 1 000 AUR pro Woche bekommt ein regelmäßiger Spieler ungefähr ein 18-€-Paket im Monat. Ein Skin kostet gut
eine Woche Spielen, der Quafe-Skin knapp einen Monat. Ein Active Booster jeden Tag (1 400 AUR pro Woche) ist damit
nicht drin, Booster bleiben gezielt eingesetzt.

## Bewertung des AUR-Stores (Stand 2026-10-26)

Ausgewertet wurden alle 526 Items mit AUR-Preis aus `CATMADB.PICKLE`; Stichproben gegen die ISK-Gegenstücke
(`baseVariation`) verglichen. Für den ganzen Store gilt:

- **Kampfwerte sind identisch** (z. B. `'Killswitch' GEK-38` vs. `GEK-38`: einziger Unterschied die Skill-Anforderung).
- **AUR-Varianten brauchen weniger Skills:** Standard 1 → 0 (176×), Advanced 3 → 1 (13×), Prototype 5 → 3 (13×).
  Man kommt früher an die Ausrüstung, sie ist aber nicht stärker.
- **Blueprints (BPOs)** sind in CATMA `consumable = False`, also unendlich nutzbar.

| Gruppe | Anzahl | AUR | Bewertung |
|---|---|---|---|
| Visual Customization (Skins) | 26, alle BPO | 6–3 480 | Harmlos: Standard-Anzug mit gleichen Werten, nur anderes Aussehen. |
| Dropsuits, Waffen, Module, Equipment, Fahrzeug-Türme, Loadouts | 245 | 3–190 | Harmlos, solange AUR knapp bleibt: verbrauchbar, gleiche Werte, nur weniger Skills. |
| Faction Booster | 28 | 160–8 100 | Harmlos: +25 % LP. |
| Militia-Blueprints | 47 BPO | 3–1 500 | Entschärfen: Infanterie okay; Fahrzeug-BPOs (Gorgon, Viper …) teurer machen oder vorerst ausblenden. |
| Active Booster | 16 | 200–2 500 | Begrenzen: +50 % Gefechts-SP, Omega +100 %. Tragbar mit SP-Wochengrenze und ohne Stapeln; Omega optional ausblenden. |
| Passive Booster | 13 | 450–6 000 | Am kritischsten: +50/100 % passive SP ohne Spielen, bis 90 Tage. Omega ausblenden, normale teuer und kurz. |
| Loyalty-Store-Items | 144 | 3–35 | Gehören nicht in den AUR-Store (Fehler unten). |

**Funde:**

1. **Fehler bei uns:** `content.aur_store()` schließt die Loyalty-Gruppe 365995 nicht aus (der ISK-Markt schon über
   `excluded_groups`). Dadurch gibt es 144 LP-Items für 3–35 AUR. **Behoben (2026-10-26):** Loyalty-Items sind im
   AUR-Store standardmäßig aus (Python und Web-Admin), einzeln per Override weiter einschaltbar; 382 statt 526 Angebote.
2. **Testartikel im Angebot:** `Passive Booster (15-minute) [QA]` (1 500 AUR) – ausblenden.
3. **Falsch bepreiste BPOs** (vermutlich Event- oder Promo-Items mit Platzhalterpreis): `X-MS Snowball Launcher`
   (Prototype-Waffe, 9 AUR, ISK-Wert 47 220), `'Dren'` Sentinel/Assault/Logistics, `'Covenant'` Assault,
   `'Quafe'` und `'Brutor'` Logistics (je 5–6 AUR). Auf einige hundert AUR anheben oder ausblenden.

**Einstellungen** (über die Overrides `enabled`/`price` pro Item im Web-Admin, außer dem Code-Fix):

- **Ausblenden:** Loyalty-Gruppe (erledigt per Code-Fix), QA-Booster, Passive Omega-Booster, Fahrzeug-Blueprints (vorerst).
- **Teurer machen:** die billigen BPOs aus Fund 3, normale Passive Booster.
- **Unverändert:** Skins, verbrauchbare AUR-Ausrüstung, Faction Booster, Infanterie-Militia-Blueprints, Active
  Booster (mit Stapel-Verbot und SP-Wochengrenze).


## Entscheidungsstand

7. **AUR-Store-Angebot:** Welche Item-Gruppen sind harmlos, welche müssen entschärft werden, und welche Werte
   gelten für Startguthaben und Wochenlimit?
   **Entscheidung des Nutzers (2026-10-26):** Bewertung und Einstellungen wie im Abschnitt „AUR-Wirtschaft“;
   Startguthaben 4 000–5 000 AUR pro Konto, etwa 1 000 AUR pro Woche durch Spielen. Offen sind nur noch die genauen
   AUR-Werte pro Match und für die Login-Belohnung.

## Ergänzung nach dem Gegenlesen (2026-10-29, Vorschlag)

- **Zweitkonten:** RPCN-Konten sind kostenlos. Auf einem offenen Server würde ein Startguthaben pro Konto immer wieder
  neu verdient, wenn jemand Zweitkonten anlegt. Auf einer privaten Runde kein Problem, bei Öffnung des Servers
  Registrierung begrenzen oder das Startguthaben an eine Bedingung knüpfen (z. B. erste abgeschlossene Matches).
- **Journal:** `aur_journal` von Anfang an anlegen (Betrag, Grund, Referenz), damit Auffälligkeiten im Web-Admin sichtbar sind.
