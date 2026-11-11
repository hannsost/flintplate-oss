# Zutaten, Merkmale und was wirklich gesperrt wird

Stand 12.09.2026. Umsetzung in `backend/app/gastro/nutrition.py`, Oberflächen in
`frontend/components/flintplate/nutrition.tsx` und im Kundenbuch, Migration `065`.

Zwei Dinge, die zusammengehören: der Kellner muss am Tisch sagen können, was in
einem Gericht ist, und der Betrieb muss auf Allergien, Diäten und Zustände eines
Gastes reagieren können.

## Ein Mechanismus, kein Sonderfall je Diät

Ein Gericht sagt, was es **enthält**: kurze Schlagworte wie `alkohol`, `gluten`,
`milch`, `schwein`, `roh`. Ein **Merkmal** eines Gastes sagt, was es **ausschließt**.
Die Prüfung ist die Schnittmenge. Eine neue Diät ist deshalb eine neue Zeile in den
Merkmalen und kein neuer Code. „Übliche übernehmen" legt einen Startsatz an:
minderjährig, schwanger, vegan, vegetarisch, halal, Nussallergie, Gluten, Laktose.
Danach gehört er dem Betrieb.

## Nur eine Sperre ist eine Sperre

| Fall | Verhalten |
|---|---|
| Alkohol bei einem als minderjährig erfassten Gast | Die Bestellung wird abgewiesen |
| Alles andere | Deutliche Warnung, die ein Mensch bestätigen kann |

Der Jugendschutz ist Gesetz, deshalb blockt er wirklich. Alles andere warnt und
lässt sich übersteuern, weil eine veraltete oder falsch erfasste Angabe sonst
einen Gast von seinem eigenen Abendessen aussperrt. Wer bestätigt, hat gesehen,
worum es geht: die Meldung nennt Gericht, Merkmal und die auslösende Zutat.

In der Kunden-App greift die Prüfung automatisch gegen das verknüpfte Gastprofil.
Bestellt der Service für einen Gast, ist die Prüfung ein Werkzeug und keine
Bevormundung: die Kartenprüfung zeigt je Artikel frei, Warnung oder gesperrt.

## Merkmale sind sensible Daten

Allergien, Schwangerschaft und religiös begründete Diäten berühren besonders
geschützte Daten. Sie verwenden dieselbe festgehaltene Einwilligung wie die
Notizen im Kundenbuch und lassen sich ohne sie nicht setzen. Das Journal hält
fest, dass Merkmale geändert wurden und wie viele es sind, niemals welche.

Vegan und vegetarisch gelten hier als gewöhnliche Vorliebe. Wer das für seinen
Betrieb anders bewertet, setzt beim Merkmal den Haken für Einwilligungspflicht.

## Zutaten am Tisch

Auf dem Bestellschirm hat jedes Gericht einen Knopf für die Zutaten. Dort stehen
die Zutaten mit ihren Allergenen und einem optionalen Hinweis, dazu die
ausgewiesenen Allergene und die Schlagworte des Gerichts. Gepflegt wird das in der
Karte, eine Zutat je Zeile in der Form `Name | Allergene | Hinweis`.

Die Liste ist eine Hilfe, kein Ersatz für die Küche. Der Dialog sagt das
ausdrücklich: bei einer ernsten Allergie wird rückgefragt.

## Der FireFlint-Vertrag bleibt unberührt

Zutaten und Schlagworte liegen im internen Artikelstand, nicht im öffentlichen
Kartensnapshot. Der an FireFlint übergebene Snapshot hat dieselbe Form wie zuvor,
und ein Test prüft genau das, damit der abgestimmte Vertrag nicht versehentlich
durch ein neues Feld bricht.

## Geprüft

Zehn HTTP-Tests decken den Startsatz samt gesetzlicher Sperre, die Zutatenliste,
die unveränderte Form des öffentlichen Snapshots, die Trennung von gesperrt und
gewarnt, die Einwilligungspflicht, unbekannte Merkmale, eine selbst angelegte
Diät, die Sperre für Alkohol bei Minderjährigen in der Kunden-App und die
Bestätigung einer Warnung durch den Gast. Migration `065` ist gegen die reale
Datenbank einschließlich Rückweg geprüft. Der Browserdurchlauf
`frontend/e2e/flintplate-nutrition.mjs` öffnet die Zutaten eines Weins am
Bestellschirm, zeigt die acht Merkmale, scheitert absichtlich an der fehlenden
Einwilligung und setzt das Merkmal nach der Einwilligung.

## Noch offen

Die Schlagworte eines Gerichts werden von Hand gepflegt und nicht aus der
Zutatenliste abgeleitet; beides nebeneinander zu führen ist eine Fehlerquelle.
Es gibt keine Mengen, keine Nährwerte und keine Zusatzstoffkennzeichnung. Die
Kunden-App zeigt die Zutaten noch nicht, und ein Gast kann seine Merkmale nicht
selbst pflegen. Bestellt der Service für einen Gast, prüft das System nicht
automatisch mit, weil eine Bestellung keine Person trägt.
