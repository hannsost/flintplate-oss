# FlintPlate lokal betreiben

FlintPlate ist ein eigenständiges Gastroprodukt mit einer Palmscout-Personalbasis.
Nur `compose.yaml` mit `.env.flintplate` verwenden; die geerbten
`docker-compose*.yml` gehören zur früheren Personalplattform.

## Vorbereitung und Start

Die vollständigen Befehle stehen im [englischen Schnellstart](../README.md#quick-start).
Zuerst lokale Schlüssel mit `python3 scripts/setup-local.py` erzeugen, das Backend-Image
bauen, Datenbank/Redis starten und den separaten `migrate`-Job ausführen. Danach API
und Frontend starten. Es wird kein vorhandenes internes Backend-Image vorausgesetzt.

| Zugang | URL |
| --- | --- |
| Betriebsleitung / Service / Küche | `http://localhost:3012/gastro` |
| Team-App | `http://localhost:3012/team` |
| Kunden-App | `http://localhost:3012/kunden/<venue_id>` |
| API-Dokumentation | `http://localhost:8012/docs` |

Der optionale synthetische Seed `python -m scripts.seed_flintplate` erzeugt lokale
Demozugänge in `backend/.local/demo-access.json` (Dateimodus 600). Diese Datei und
`.env.flintplate` niemals veröffentlichen. QuickWork und zugehörige Personen/Firmen
in geerbten Testdaten sind ebenfalls erfunden.

Stoppen: Frontend-Prozess beenden, dann
`docker compose -f compose.yaml --env-file .env.flintplate down`.
Ohne `-v` bleiben Datenvolumes erhalten.

## Mobile Nutzung

Getrennte installierbare Web-Apps für Betrieb, Mitarbeitende und Gast je Betrieb.
iPhone: Safari → Teilen → Zum Home-Bildschirm; Android: Browserinstallation.
Abseits von localhost ist HTTPS erforderlich. Ein Smartphone erreicht den
Linux-Rechner nicht über sein eigenes `localhost`; dafür braucht die Umgebung
eine passende HTTPS-Adresse. App-Store-Builds sind noch nicht erzeugt.

Der Service Worker liefert bei Verbindungsausfall eine allgemeine Offline-Seite.
Er speichert keine Gast-/Personal-/Bestelldaten und führt keine Offlinebuchungen
automatisch aus. Bei unklarem Bestellausgang verwendet die Wiederholung dieselbe
Vorgangs-ID. Auch der lokale Produktionsbuild ist noch kein öffentlicher
SaaS-Produktionsbetrieb.

## Integrationen

FireFlint benötigt `FIREFLINT_BASE_URL`, einen separat verwalteten
`FLINTPLATE_CONNECTOR_KEY` (Fernet) und je Verbindung die berechtigten
Management-Tokens. Instanz und Publikation werden vom Betreiber konfiguriert. Format: `FIREFLINT-MENU-SNAPSHOT-V1.md`.

Gerätezugänge werden von der Leitung pro Betrieb erstellt. Der Klartextschlüssel
ist nur bei Erstellung sichtbar; Speicherung in der Datenbank erfolgt als Hash.
Scopes, Ablaufdatum und Widerruf gelten für die versionierten Geräteendpunkte
unter `/device/v1`. Konkrete Hersteller müssen ihre Adapter gegen diese API
testen; ein vorhandener Netzwerkanschluss beweist keine Kassenkompatibilität.

Vertretungsanfragen und Fristwechsel sind persistent. Mit
`FLINTPLATE_REPLACEMENT_WORKER=true` prüft die API offene Suchen alle 15 Sekunden;
Datenbanksperren koordinieren parallele Instanzen. Angeboten wird aktuell in der
Team-App, keine externe Push-/SMS-Zustellung.

## Prüfungen und Journal

```bash
docker compose -f compose.yaml --env-file .env.flintplate exec -T api python -m scripts.test_flintplate
python scripts/verify-journal.py /pfad/zum/flintplate-journal.json
```

Der Testrunner erzwingt `flintplate_test`; Tests erzeugen ihr eigenes Schema.
Journalexporte enthalten personenbezogene Akteure und gehören in die berechtigte
Verwaltung. Der Prüfer kontrolliert Hashkette, Felder, Zeitstempel und Anker.
Ein unabhängig archivierter letzter Hash hilft, spätere Kürzungen zu erkennen.
DB-Owner können Schutztrigger abschalten; Produktivbetrieb braucht getrennte
Datenbankrollen, Backups und unabhängig gesicherte Anker. Dies ersetzt keine TSE.
