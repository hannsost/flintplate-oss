# Team-Chat

Stand 12.09.2026. Umsetzung in `backend/app/gastro/chat.py`, Oberfläche in
`frontend/components/flintplate/chat.tsx`, Migration `066`.

Kurze Absprachen während der Schicht, in derselben Anwendung wie Dienstplan und
Bestellungen. Absichtlich klein: Kanäle, Nachrichten, gelesen-bis.

## Was es kann

Jede Betriebsstätte bekommt beim ersten Öffnen einen Kanal „Team". Die Leitung
legt weitere an, etwa „Küche" für Absprachen am Pass. Nachrichten erscheinen in
der Betriebsoberfläche unter Team und Dienste sowie in der Team-App als eigener
Reiter. Beide Ansichten holen alle zwölf Sekunden nach, solange sie sichtbar sind;
im Durchlauf lagen neun Sekunden zwischen Absenden auf dem Telefon und Erscheinen
am Rechner.

Ungelesenes wird je Kanal gezählt, aber nur, was andere geschrieben haben. Beim
Öffnen eines Kanals gilt er als gelesen.

## Was es bewusst nicht kann

**Kein Bearbeiten.** Eine Nachricht lässt sich löschen, aber nicht umschreiben.
Wer nachträglich ändern könnte, was er geschrieben hat, macht den Verlauf
wertlos. Eigene Nachrichten löscht jeder selbst, fremde nur die Betriebsleitung,
und dieser Fall wird im Betriebsjournal festgehalten.

Keine Direktnachrichten zwischen zwei Personen, keine Dateianhänge, keine
Erwähnungen, keine Push-Benachrichtigung bei geschlossener App. Das ist ein
Dienstchat, kein Messenger.

## Aufbewahrung

Auch ein Dienstchat enthält personenbezogene Daten, häufig über Gäste und
Kollegen. Jede Nachricht bekommt beim Schreiben ein Ablaufdatum aus der
Aufbewahrungsdauer der Betriebsstätte, voreingestellt 90 Tage, einstellbar
zwischen 7 und 730 Tagen. Abgelaufene Nachrichten werden nicht mehr angezeigt und
lassen sich endgültig entfernen.

Die Reihenfolge und der Ungelesen-Zähler hängen an einer fortlaufenden Nummer, an
keinem Zeitstempel. Zwei Nachrichten in derselben Sekunde bleiben dadurch in der
Reihenfolge, in der sie geschrieben wurden.

## Geprüft

Acht HTTP-Tests decken den automatisch angelegten Kanal, Reihenfolge und
Zuordnung zum Verfasser, den Ungelesen-Zähler samt Lesemarke, das Löschrecht,
den Ablauf mit endgültiger Entfernung, die Grenzen der Aufbewahrungsdauer, den
zweiten Kanal mit eindeutigem Namen und die Unsichtbarkeit für Betriebsfremde.
Migration `066` ist gegen die reale Datenbank einschließlich Rückweg geprüft.
Der Browserdurchlauf `frontend/e2e/flintplate-chat.mjs` schreibt am Rechner,
liest auf dem Telefon, antwortet dort und misst, wie lange die Antwort bis zum
Rechner braucht.
