# Bestellen am Tisch, zahlen im Handy, Trinkgeld verteilen

Stand 11.09.2026. Umsetzung in `backend/app/gastro/guests.py` und
`backend/app/gastro/tips.py`, Oberflächen in `frontend/app/kunden/[venueId]/page.tsx`
und `frontend/components/flintplate/tips.tsx`, Migration `063`.

Vorher konnten Gäste ausschließlich zur Abholung bestellen, und bezahlen ging im
Handy überhaupt nicht. Beides war ein bewusster Riegel im Code, kein Versehen.

## Am Tisch bestellen

Die Betriebsleitung gibt die Tischbestellung je Betriebsstätte frei. Danach wählt
der Gast in der Kunden-App zwischen Abholung und „Vor Ort" und bekommt bei „Vor
Ort" eine Tischliste. Ohne Freigabe bleibt es bei der bisherigen Antwort, dass
Tischbestellungen den Service benötigen.

Zweiter Schalter: ob ein Gast an jedem Tisch bestellen darf oder nur an dem, an
dem er nachweislich sitzt. Standard ist die strengere Variante, die eine eigene
Reservierung im Zustand „eingecheckt" an genau diesem Tisch verlangt. Sonst
könnte jemand auf fremde Rechnung bestellen. Jede Bestellung trägt das Gastkonto
und steht damit im Journal.

## Zahlen im Handy

**FlintPlate bucht kein Geld ab.** Es ist kein Zahlungsanbieter angebunden, und
die Oberfläche behauptet das auch nicht. Der Gast wählt an einem servierten Bon
ein Trinkgeld, kein Trinkgeld, fünf Prozent, zehn Prozent oder einen eigenen
Betrag, und schickt den Bon damit an die Kasse. Die Kasse bestätigt anschließend
über die bestehende Geräteschnittstelle, was sie tatsächlich kassiert hat.

Die Betragsprüfung dieser Bestätigung schließt das Trinkgeld ein: die Kasse muss
Rechnungsbetrag abzüglich Gutschein zuzüglich Trinkgeld melden, sonst wird die
Zahlung abgewiesen. Damit kann ein angefordertes Trinkgeld nicht stillschweigend
verschwinden.

Ein echter Zahlungsanbieter wird später angebunden. Der Weg dorthin ändert sich
dadurch nicht: der Bon trägt bereits Betrag, Währung, Referenz und eine
Idempotenz-ID, und mehrere Anbieter können nacheinander an dieselbe Stelle
gehängt werden. Sobald wirklich kassiert wird, greifen Fiskalisierung und
Belegpflicht; beides ist nicht umgesetzt.

## Trinkgeld verteilen

Je Betriebsstätte gilt eine von zwei Regeln.

| Regel | Verteilung |
|---|---|
| Topf nach Stunden | Alles Trinkgeld eines Zeitraums wird nach tatsächlich erfassten Arbeitsminuten geteilt, mit optionalem Küchenanteil. |
| Direkt | Das Trinkgeld eines Bons geht an die Person, die ihn abgeschlossen hat oder die ausdrücklich eingetragen wurde. |

Verteilt wird nur, was bestätigt bezahlt ist. Grundlage sind die erfassten Zeiten
aus der Zeiterfassung, nicht der Dienstplan: wer eingeteilt war, aber nichts
erfasst hat, erscheint mit null und dem sichtbaren Grund. Beträge werden nach dem
größten Rest verteilt, sodass die Summe der Anteile exakt dem Topf entspricht.

Fällt im Modus „direkt" Trinkgeld ohne erfasste Bedienung an, verschwindet es
nicht, sondern geht in den Stundentopf, und die Vorschau sagt das. Ist ein
Küchenanteil eingestellt, aber keine Küchenzeit erfasst, bleibt der Anteil beim
Service, ebenfalls mit Hinweis.

Die Vorschau schreibt nichts. Erst das Festschreiben legt den Lauf an, hängt jeden
Anteil mit Minuten und Begründung daran und markiert die verteilten Bons, damit
dasselbe Trinkgeld nie zweimal verteilt wird. Ein Zeitraum kann genau einmal
festgeschrieben werden. Der Lauf schreibt ein Ereignis in die Hashkette des
Betriebsjournals.

## Bewusst nicht umgesetzt

Die Auszahlung selbst führt FlintPlate nicht aus, weder bar noch über die
Lohnabrechnung. Die steuerliche Behandlung von Trinkgeld unterscheidet sich
danach, ob es freiwillig von Dritten an die Person geht oder ob der Arbeitgeber
einen Topf verteilt. Diese Einordnung gehört zur Steuerberatung des Betriebs und
wird hier nicht entschieden und nicht behauptet. FlintPlate hält fest, was
eingegangen ist und wie es aufgeteilt wurde.

Ebenfalls offen: Kartenzahlung im Handy, Splitten einer Rechnung auf mehrere
Gäste, Trinkgeld nachträglich zu einem bereits bezahlten Bon, und eine eigene
Auswertung über längere Zeiträume.

## Geprüft

Zehn HTTP-Tests decken die Tischfreigabe, den Schutz fremder Tische, die
Sitzungsbindung, das Trinkgeld in der Betragsprüfung der Kasse, die Eintragung
durch den Service, die Verteilung nach Minuten mit exakter Summe, den
Küchenanteil ohne Küchenzeit, die Einmaligkeit eines Laufs und den direkten Modus.
Migration `063` ist gegen die reale Datenbank einschließlich Rückweg geprüft.
Der Browserdurchlauf `frontend/e2e/flintplate-tip-journey.mjs` spielt den ganzen
Weg durch: Freigabe in der Betriebsoberfläche, Tischbestellung vom Telefon,
Servieren, Zahlung mit zehn Prozent Trinkgeld, Kassenbestätigung über die
Geräteschnittstelle und die festgeschriebene Verteilung.
