# Was von selbst passiert

Stand 11.09.2026. Umsetzung in `frontend/components/flintplate/shared.tsx`
(`useLive`, `useNow`), `operations.tsx`, `panels.tsx` und der Kunden-App.

Vorher musste man in der Kunden-App und in der Team-App auf einen Knopf drücken,
um zu sehen, ob sich etwas getan hat. Das ist die Art Arbeit, die Software
abnehmen soll.

## Ansichten halten sich selbst aktuell

Kunden-App und Team-App laden alle fünfzehn Sekunden nach, aber nur, solange die
Seite wirklich sichtbar ist. Wechselt jemand den Tab oder legt das Telefon weg,
hört das Nachladen auf und setzt beim Zurückkommen sofort wieder ein. Ein
fehlgeschlagener Hintergrundabruf bleibt still und versucht es beim nächsten Mal;
eine Aktion, die jemand ausgelöst hat, meldet ihren Fehler weiterhin sichtbar.

Die Betriebsoberfläche hatte diesen Takt schon. Neu ist eine eigene Uhr, die
verstrichene Zeiten weiterzählt, ohne dafür Daten zu holen.

## Der Gast sieht, wo seine Bestellung steht

Statt eines Statusworts steht unter jeder Bestellung ein Verlauf: Eingegangen,
Wird zubereitet, Fertig, Serviert, Bezahlt. Bei Abholung heißen die Schritte
Abholbereit und Übergeben. Daneben steht, seit wann. Solange die Küche noch nicht
begonnen hat, kann der Gast seine Bestellung selbst zurücknehmen; danach verweist
die Meldung an den Service, statt den Knopf einfach zu verstecken.

## Die Betriebsoberfläche zeigt, was jetzt dran ist

Über den Kennzahlen steht, was auf einen Menschen wartet: Bons, die auf die Kasse
warten, fertige Bestellungen, die seit mehr als fünf Minuten nicht serviert sind,
und Bestellungen, mit denen die Küche nach zehn Minuten noch nicht begonnen hat.
Jeder Eintrag führt mit einem Klick dorthin. Wartet nichts, steht dort auch nichts
Dringliches, sondern der Hinweis, dass sich die Ansicht selbst aktuell hält.

## Küche und Grundriss zeigen Zeit statt Zustand

Jedes Küchenticket trägt seine Minuten. Ab zehn Minuten wechselt die Kante die
Farbe, ab zwanzig deutlicher, und die Tickets stehen in der Reihenfolge ihres
Eingangs. Zahlen und Farbe sagen dasselbe, damit es auch ohne Farbwahrnehmung
lesbar bleibt.

Der Grundriss unterscheidet jetzt vier Zustände statt zwei: frei, in der nächsten
Stunde reserviert mit Uhrzeit, belegt mit der Dauer, und Zahlung angefordert. Der
Zustand steht als Text auf der Kachel und in der Vorlesebeschriftung, nicht nur
als Farbe.

## Geprüft

Der Browserdurchlauf `frontend/e2e/flintplate-live-ux.mjs` bestellt als Gast an
den Tisch, lässt die Küche über die Schnittstelle beginnen und wartet, bis das
Telefon den neuen Schritt von selbst zeigt. Gemessen wurden vierzehn Sekunden
ohne jede Eingabe. Danach prüft er die Aufmerksamkeitsleiste, den Tisch mit
angeforderter Zahlung und die Minutenanzeige auf dem Küchenticket. Keine
JavaScript-Fehler, kein horizontales Überlaufen. Das Zurücknehmen einer
Bestellung ist zusätzlich durch einen HTTP-Test abgedeckt.

## Noch offen

Es gibt keine Push-Benachrichtigung, wenn die App geschlossen ist, und keine
Verbindung über WebSockets; die Aktualisierung ist Abfrage im Takt. Ein sichtbarer
Offlinezustand mit Warteschlange für abgeschickte Aktionen fehlt weiterhin.
