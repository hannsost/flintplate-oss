# Profilvorlagen für das Team

Stand 11.09.2026. Umsetzung in `backend/app/gastro/profiles.py`, Oberfläche in
`frontend/components/flintplate/profiles.tsx`, Migration `062`.

Eine Vorlage hält das, was sich bei mehreren Personen wiederholt: die Stationen
und die Erfahrungsstufe. Personen erben davon, dürfen aber jedes Feld einzeln
übernehmen. Woher ein Wert kommt, steht an jedem Feld.

## Was eine Vorlage ausdrücklich nicht enthält

Die Rolle in der Betriebsstätte und die freiwillige Bereitschaft für
Vertretungsanfragen sind kein Teil einer Vorlage und werden auch beim Kopieren von
Person zu Person nicht übertragen. Die Rolle entscheidet über Rechte; sie soll
nicht durch das Anwenden einer Vorlage auf eine Gruppe wandern. Die Bereitschaft
gehört der Person, und Freiwilligkeit, die das Management setzen kann, wäre keine.

## Erben, überschreiben, lösen

Geerbte Werte werden auf den Mitgliedsdatensatz geschrieben, nicht nur beim Lesen
berechnet. Damit sehen alle vorhandenen Leser denselben Wert, insbesondere die
Vertretungssuche, die Station und Kompetenz direkt auswertet.

| Zustand | Bedeutung |
|---|---|
| geerbt | Das Feld folgt der Vorlage und ändert sich mit ihr. |
| eigen | Das Feld wurde persönlich gesetzt und folgt der Vorlage nicht mehr. |
| ohne Vorlage | Alle Felder sind persönlich. |

Ein Klick auf „geerbt“ löst genau dieses Feld, ein Klick auf „eigen“ hängt es
wieder an. Wird die Vorlage ganz gelöst, bleiben die zuletzt geerbten Werte als
persönliche Werte stehen; es entsteht keine Lücke.

## Vorschau vor dem Anwenden

Das Ändern einer Vorlage ist ein Eingriff in mehrere Personalakten. Deshalb zeigt
die Oberfläche vorher, was sich für wen ändert, mit altem und neuem Wert, und wer
wegen eigener Werte unberührt bleibt. Erst die Bestätigung schreibt. Die Vorschau
läuft über einen eigenen Endpunkt und verändert nichts.

## Von einer Person übernehmen

Das Kopieren von Person zu Person ist derselbe Mechanismus: Stationen, Erfahrung,
die Vorlagenbindung und die persönlich gesetzten Felder werden gespiegelt. Es
entsteht kein zweiter Weg, an dem sich Werte anders verhalten.

## Grenzen und Ereignisse

Vorlagennamen sind je Betriebsstätte eindeutig. Eine Vorlage, von der noch jemand
erbt, lässt sich nicht löschen. Änderungen prüfen die Version und weisen einen
veralteten Stand mit 409 ab. Anlegen, Ändern, Zuweisen, Kopieren und Entfernen
schreiben jeweils ein eigenes Ereignis in das Betriebsjournal.

## Geprüft

Elf HTTP-Tests decken Eindeutigkeit, Vererbung, Materialisierung bis in die
bestehende Qualifikationsansicht, die Vorschau ohne Schreibwirkung, den Schutz
durch eigene Werte, das Wiederanhängen, das Lösen der Vorlage, das Kopieren
einschließlich unveränderter Rolle und Bereitschaft, die Löschsperre und die
Versionsprüfung ab. Migration `062` ist gegen die reale Datenbank einschließlich
Rückweg geprüft. Der Browserdurchlauf `frontend/e2e/flintplate-profiles.mjs` legt
eine Vorlage an, weist sie zu, löst ein Feld, ändert die Vorlage über die
Vorschau und bestätigt danach, dass der persönliche Wert erhalten blieb.

## Noch offen

Vorlagen umfassen bisher nur Stationen und Erfahrungsstufe. Vertragsdaten,
Sollstunden, Zuschlagsregeln und Wunschzeiten liegen im Palmscout-Personalstamm
und sind nicht angebunden. Es gibt keine Vorlagenhierarchie, keine zeitlich
geplante Gültigkeit und keine Massenzuweisung an mehrere Personen auf einmal.
