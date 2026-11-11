# Kundenbuch

Stand 11.09.2026. Umsetzung in `backend/app/gastro/guestbook.py`, Oberfläche in
`frontend/components/flintplate/guestbook.tsx`, Migration `064`.

Stammgäste wiedererkennen, Vorlieben und Gespräche behalten, und den Kollegen im
nächsten Dienst mitgeben, was zählt. Ohne daraus ein Archiv über Menschen zu machen.

## Was gespeichert wird

Ein Eintrag besteht aus Ansprache, einer Merkhilfe für das Team und freiwillig
einem Geburtstag als Tag und Monat. **Kein Geburtsjahr, keine Adresse, keine
Telefonnummer.** Zum Wiedererkennen und Gratulieren reicht das; alles darüber
hinaus wäre Sammeln ohne Zweck. Ein Jahr im Geburtstagsfeld wird abgewiesen.

Dazu kommen datierte Notizen mit einer Art: Vorliebe, Anlass, Gespräch, Hinweis
für den Service, Gesundheit, Ernährung.

## Sichtbarkeit ist keine Geheimhaltung

Eine Notiz ist entweder für das ganze Serviceteam sichtbar oder „nur für mich".
Das ist eine Sichtbarkeit im Haus, keine Zusage, dass die Notiz unerreichbar ist.
Verantwortlich bleibt der Betrieb. Die Oberfläche sagt das an der Stelle, an der
man es liest: der Gast kann Auskunft verlangen, dann steht die Notiz in der
Auskunft, und die Betriebsleitung kann sie löschen. Eine Software, die hier
Vertraulichkeit verspricht, würde das Team belügen.

## Gesundheit und Ernährung brauchen Einwilligung

Hinweise auf Allergien, Unverträglichkeiten oder eine Ernährungsweise berühren
besonders geschützte Daten. Solche Notizen weist die Schnittstelle ab, solange
für diese Person keine Einwilligung festgehalten ist. Wer die Einwilligung
einträgt und wann, wird mitgespeichert.

Ein Widerruf entfernt die Grundlage, also entfernt er auch die Notizen, die
darauf beruhten. Das passiert sofort und vollständig, nicht als Markierung.
Andere Notizen bleiben unberührt.

## Vergessen ist eingebaut

Jede Notiz bekommt beim Anlegen ein Ablaufdatum aus der Aufbewahrungsdauer der
Betriebsstätte, voreingestellt ein Jahr, einstellbar zwischen 30 und 1095 Tagen.
Abgelaufene Notizen werden nicht mehr angezeigt und lassen sich endgültig
entfernen. Das Löschen einer Person nimmt alle ihre Notizen mit; das Ereignis im
Journal hält fest, dass gelöscht wurde und wie viele Einträge betroffen waren,
niemals aber deren Inhalt.

## Nachschlagen ist nachvollziehbar

Das Öffnen eines Eintrags schreibt `guestbook.viewed` in die Ereigniskette des
Betriebsjournals, mit Person, Zeitpunkt und Anzahl der gezeigten Notizen. Wer
jemanden nachschlägt, hinterlässt damit dieselbe Spur wie jemand, der einen Preis
ändert. Das ist gegen Neugier gerichtet, nicht gegen die Arbeit.

## Auskunft und Berichtigung

Die Betriebsleitung erzeugt eine vollständige Auskunft als Datei: Stammdaten,
alle Notizen einschließlich der persönlichen und der abgelaufenen, Zeitpunkt der
Erstellung. Damit lässt sich eine Auskunftsanfrage beantworten, ohne in der
Datenbank zu suchen. Angaben zur Person lassen sich versionsgeprüft berichtigen.

## Was dieses Dokument nicht leistet

Es ersetzt weder ein Verarbeitungsverzeichnis noch eine Datenschutzerklärung noch
die Prüfung durch eine fachkundige Person. Die Software stellt die technischen
Mittel bereit: Zweckbindung durch Kategorien, Einwilligung als Vorbedingung,
Löschfristen, Auskunft, Löschung und ein Zugriffsprotokoll. Welche Rechtsgrundlage
der Betrieb wählt und wie er die Gäste informiert, entscheidet der Betrieb.

## Geprüft

Zehn HTTP-Tests decken Suche, die Abweisung eines Geburtsjahrs, die Sperre für
Gesundheitsnotizen ohne Einwilligung, das gezielte Löschen beim Widerruf, die
Sichtbarkeit persönlicher Notizen gegenüber Kollegen und in der Auskunft, das
Löschrecht an fremden Notizen, den Ablauf samt endgültiger Entfernung, den
Journaleintrag beim Öffnen, die vollständige Löschung ohne Inhalt im Ereignis und
die Grenzen der Aufbewahrungsdauer. Migration `064` ist gegen die reale Datenbank
einschließlich Rückweg geprüft. Ein Browserdurchlauf legt einen Gast an, scheitert
absichtlich an der fehlenden Einwilligung, hält sie fest, schreibt Notizen und
widerruft wieder: `frontend/e2e/flintplate-guestbook.mjs`.

## Noch offen

Der Gast sieht seinen eigenen Eintrag nicht in der Kunden-App; die Auskunft läuft
über die Betriebsleitung. Notizen lassen sich nicht bearbeiten, nur schreiben und
löschen, damit nichts unbemerkt umgedeutet wird. Es gibt keine automatische
Verknüpfung mit Reservierungen oder Bestellungen, keine Erinnerung zum Geburtstag
und keine Übernahme zwischen Betriebsstätten.
