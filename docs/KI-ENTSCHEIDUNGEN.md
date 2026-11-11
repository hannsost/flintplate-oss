# Entscheidungsebene · Tischvorschlag für Reservierungen

Stand 11.09.2026. Umsetzung in `backend/app/gastro/decisions.py`, Oberfläche in
`frontend/components/flintplate/seating.tsx`, Migration `061`.

Die Ebene schlägt vor und bucht nichts von selbst. Sie liefert drei benannte
Optionen mit sichtbaren Gründen und Nachteilen. Erst die ausdrückliche Annahme
legt eine Reservierung an, und dabei werden alle Regeln erneut gegen den dann
aktuellen Stand geprüft.

## Verbindliche Grenze

Harte Regeln filtern zuerst und sind nicht verhandelbar: Sitzplatzzahl,
Mindestgruppengröße, Angebotsart und ein freies Zeitfenster ohne überlappende
Reservierung oder laufende Nutzung. Ein Prompt oder ein Sprachmodell kann
ausschließlich Gewichte verschieben und Merkmale bevorzugen. Es kann keine
Ressource zulassen, die die Regeln ausschließen, keine Ressource erfinden und
kein belegtes Fenster öffnen. Ein Modell erhält nie Gastnamen oder Bestelldaten,
sondern nur den freien Text und die im Betrieb bekannten Merkmalsnamen.

## Die drei Optionen

| Option | Optimiert auf |
|---|---|
| Beste Passung | Passgenaue Sitzplatzzahl, möglichst wenig verschenkte Plätze |
| Hält den Abend offen | Kombinierbare Nachbartische bleiben für größere Gruppen frei |
| Nächster Wunsch | Gewünschte Merkmale und der gewünschte Bereich zuerst |

Jede Option nennt zuerst ihren eigenen Zweck, danach die konkreten Gründe und
getrennt davon die Nachteile. Ein blockierter Kombinationsverbund und ein
unterschrittener Rückhalt für Laufkundschaft erscheinen ausdrücklich als Nachteil,
nicht als verstecktes Kriterium. Gibt es weniger unterscheidbare Ressourcen als
Optionen, kommen weniger als drei Vorschläge zurück.

Passt im gewünschten Fenster nichts, wird nicht einfach abgelehnt. Geprüft werden
Verschiebungen um jeweils 30 und 60 Minuten nach vorne und hinten; die Rückgabe
benennt die geänderte Zeit. Passt keine einzelne Ressource, werden als
kombinierbar gepflegte Nachbarn zu einem Vorschlag zusammengestellt.

## Freier Text und gespeicherte Kriterien

Der freie Text beschreibt zusätzliche Punkte für genau diese Entscheidung.
Unter `decision-criteria` hinterlegt die Betriebsleitung wiederverwendbare
Kriterien, die jeder späteren Anfrage angehängt werden. Beides wird mit dem
Vorschlag gespeichert.

Ohne eingerichteten Modellzugang wird der Text gespeichert, aber nicht angewendet.
Die Antwort sagt das ausdrücklich und kennzeichnet die Vorschläge als regelbasiert.
`engine` ist dann `rules`, sonst `rules+model`, und `prompt_applied` unterscheidet
beide Fälle. Ein Modellfehler führt nie zum Abbruch, sondern zurück auf die Regeln.

## Nachvollziehbarkeit

Jeder Vorschlag wird als Datensatz gespeichert: Anfrage, alle Optionen, Prompt,
verwendete Ebene und später die getroffene Auswahl mit Zeitpunkt. Zusätzlich
schreiben `decision.proposed` und `decision.accepted` in die vorhandene
Ereigniskette des Betriebsjournals. Ein Vorschlag kann genau einmal angenommen
werden; ein zweiter Versuch endet mit 409.

## Stammdaten, die den Nutzen bestimmen

Migration `061` ergänzt je Ressource frei wählbare Merkmale, eine
Mindestgruppengröße und die Liste kombinierbarer Nachbarn, je Betriebsstätte eine
Standardverweildauer und einen Rückhalt an Plätzen für Laufkundschaft.
Kombinierbare Nachbarn müssen zur selben Betriebsstätte gehören; ein Tisch kann
nicht mit sich selbst kombiniert werden. Solange weder Merkmale noch Kombinationen
gepflegt sind, weist die Antwort darauf hin, dass sich die Optionen nur in der
Ressource selbst unterscheiden können.

## Geprüft

Zwölf HTTP-Tests decken Auswahl, unterscheidbare Begründungen, Ausschluss belegter
und zu kleiner Ressourcen, Schutz eines Kombinationsverbunds, Zusammenstellung für
große Gruppen samt strengster Mindestgruppengröße, Zeitverschiebung, einmalige
Annahme, erneute Prüfung einer zwischenzeitlich vergebenen Ressource,
Prompt-Kennzeichnung und gespeicherte Kriterien ab.
Migration `061` wurde gegen die reale Datenbank einschließlich Rückweg geprüft.
Ein Browserdurchlauf legt über die Oberfläche eine Reservierung aus einem
Vorschlag an; Beleg in `frontend/e2e/flintplate-seating.mjs`.

## Noch offen

Verweildauer wird als fester Betriebswert angenommen und nicht aus tatsächlichen
Nutzungen gelernt. Gastvorlieben und Stammgasthistorie fließen noch nicht ein.
Das Umplanen nach Absagen, das Platzieren beim Eintreffen abweichender
Gruppengrößen und der Vorschlag in der Kunden-App sind nicht umgesetzt. Die
Entscheidungsebene ist bisher nur an die Reservierung angeschlossen; Dienstplan,
Vertretungssuche und Küchenreihenfolge verwenden sie noch nicht. Bei einer
Kombination entstehen derzeit mehrere Reservierungen mit demselben Gastnamen statt
eines gemeinsamen Vorgangs.
