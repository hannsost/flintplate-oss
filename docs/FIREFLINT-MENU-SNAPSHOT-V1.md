# FlintPlate → FireFlint · Snapshot v1

Implementierung: `backend/app/gastro/fireflint.py`; maschinenlesbarer Vertrag:
`FIREFLINT-MENU-SNAPSHOT-V1.schema.json`. Schemaexport am 11.09.2026.

FlintPlate bleibt Autorität für Preis, Steuer, Verfügbarkeit, Bestellung und Personal.
FireFlint verantwortet redaktionelle Website-Inhalte, Ausnahmen und explizite Publikation.
Apps, Datenbanken und Anmeldung bleiben getrennt. Kein gemeinsamer JWT-Zwang.

| Feld | Bedeutung |
|---|---|
| `schema_version` | Konstante Ganzzahl `1` |
| `source_system` | Konstante `flintplate` |
| `venue_id`, `menu_id` | UUID-Strings; v1 hat eine Karte pro Betriebsstätte, IDs sind identisch |
| `menu_revision` | SHA-256 als 64 kleine Hexzeichen; opaker Inhaltsstand, keine Reihenfolge |
| `currency` | v1 ausschließlich `EUR` |
| `timezone` | IANA-Zeitzone der Betriebsstätte |
| `published_at` | UTC-Zeit der Erstellung dieses Übertragungssnapshots, keine FireFlint-Publikation |
| `items` | Öffentliche, veröffentlichte Artikelsnapshots gemäß JSON-Schema |

Artikel enthalten UUID `id`, `sku`, ganzzahlige `version`, Name/Beschreibung/Kategorie,
`price_cents`, `tax_rate_bps`, Allergene, Verfügbarkeit, Station und optional
`takeaway_packaging`. `1900` Basispunkte bedeutet 19 Prozent. Verpackung und Pfand
tragen jeweils ihren eigenen konfigurierten Preis/Steuersatz. Einkaufspreise,
Mitarbeitende und Bestelldaten sind kein Teil dieses Snapshots.

## Exakte Hashbildung

1. Öffentliche Artikelsnapshots nach ASCII-SKU aufsteigend sortieren, unabhängig von DB-Collation.
2. Artikel einschließlich ihrer Modell-Defaults und `null`-Werte in JSON-Modus serialisieren.
3. Python-kompatibles `json.dumps(items, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
4. SHA-256 über die UTF-8-Bytes dieses Strings, als kleines Hex ausgeben.

Nur `items` gehen in den Hash ein. Ein neuer Übertragungszeitpunkt allein ändert ihn
nicht. Empfänger dürfen die Revision als opak behandeln. Dies ist keine Behauptung
von RFC-8785-Kanonisierung. Das JSON-Schema beschreibt Feldtypen; die Artikel werden
aus validierten veröffentlichten FlintPlate-Daten erzeugt.

## Bereits implementierter Managementadapter

- Serverseitig konfigurierte FireFlint-Basisadresse und verschlüsselte Connector-Tokens.
- Management mit Access-JWT eines berechtigten Editors/Owners. Einrichtung von Typ
  und Website bleibt Owner-Aufgabe; Typanlage erwartet `fields`.
- `PUT /api/orgs/{org}/content/{type}/{id}` mit `{data, expected_revision}`.
- Expliziter separater Publish-Aufruf liefert Status 200 und vollständiges ContentObject.
- Refresh erneuert nur `access_token`; das vorhandene Refresh-Token bleibt erhalten.
- Content-ID, Organisation, Rückgaberevision und rückgemeldeter Snapshot werden geprüft.
- Quell-Hash, FireFlint-Revision und lokale Adapterversion sind getrennt.
- 409 führt zum Konfliktzustand. Timeout oder unplausible Write-Antwort führt zu
  ungeklärtem Zustand. Keine blinde Wiederholung und kein automatisches Neubasieren.

Channel-PUT-Rückgaben müssen beim späteren Channeladapter unter `content.revision`
ausgelesen werden. Delivery liefert `{items:[effective data]}` ohne automatisch
ergänzte ContentObject-Metadaten. Tiefe generische Itemvalidierung und generische
Create-Idempotenz werden bei FireFlint nicht vorausgesetzt.

## Noch offen

Der Rückkanal eines gemeinsamen Karteneditors, Channelverwaltung, Einrichtung neuer
Content-Typen/Websites und ein ausgeliefertes gemeinsames TypeScript-SDK sind weitere
Implementierungsarbeit. Die bisherigen Adaptertests verwenden HTTP-Mocks; eine echte
FireFlint-Instanz wurde weder konfiguriert noch beschrieben oder veröffentlicht.
