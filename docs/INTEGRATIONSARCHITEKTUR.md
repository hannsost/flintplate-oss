# Herstelleradapter und nächste Abnahmen

## Bereits laufende Integrationsgrenzen

FlintPlate hat eigene Mandanten, Betriebsrechte, Datenbank, Gerätezugänge und ein
persistentes Betriebsjournal. Palmscout-Personalidentitäten und Einsatzplanung sind
intern verbunden. FireFlint wird über einen eigenen Managementadapter angesprochen.
Die HTTP-API ist unter `/docs` verfügbar; Herstelleradapter erhalten eigene
Geräteschlüssel mit eng begrenzten Scopes, Gültigkeit und Widerruf.

Der Linux-Server stellt Web-Apps für Browser/Handhelds bereit. Windows-Clients
können dieselbe Oberfläche nutzen. Proprietäre Ordergeräte benötigen jeweils
einen kompatiblen Browser oder einen Herstelleradapter; keine pauschale Zusage.

## POS und Geräte

Bereits implementiert sind veröffentlichte Artikel, Ressourcen, autorisierte
Bestell-/Küchenkommandos, paginierte Ereignisse und idempotente Zahlungseingänge.
Zahlungsrückmeldungen prüfen Währung und offenen Restbetrag. Gutscheine sind
Zahlungsmittel; Pfand wird nicht mit einem freien Produktrabatt reduziert.
Journal und Bestell-Snapshots ermöglichen Abgleich, ersetzen keine Fiskalschnittstelle.

Abnahme je Kassenhersteller: Zuordnung der Artikel und Steuern, Payment-ID,
Verhalten bei Timeout/Wiederholung, Teil-/Splitzahlungen, Storno/Retoure nach
Fiskalisierung, Trinkgeld, Kassenabschluss, Kassensturz, TSE und DSFinV-K.
Anschließend gemeinsamer Test mit konkreter Hardware/Firmware und Herstellerzugang.

## Küchen- und Serviceroboter

Ein Roboteradapter soll Aufgaben an das Hersteller-System geben; Motorsteuerung,
Kollisionsvermeidung und der physische Not-Halt bleiben beim Hersteller. Der
Personal-Vertretungsknopf ist ausdrücklich kein physischer Roboter-Not-Halt.

Vorgesehener Auftrag: Betrieb, Geräte-ID, Idempotenzschlüssel, benötigte Fähigkeit,
freigegebener Abhol-/Zielpunkt, Frist und optional Bestell-/Tablettbezug. Keine
Gastnamen, Zahlungsdaten oder freie KI-Bewegungskommandos an Geräte übertragen.
Herstellerkarten/Koordinaten müssen ausdrücklich auf FlintPlate-Räume und
Stockwerke abgebildet werden; ein gezeichneter Tischplan ist keine Navigationskarte.

Geplanter Lebenszyklus: angelegt → zur Übernahme angeboten → angenommen →
unterwegs → Übergabe bestätigt → abgeschlossen. Fehler, Ablauf und Abbruch
erhalten eigene Ereignisse. Unklarer Ausgang braucht Statusabgleich vor erneuter
Zustellung. Ein Roboterstatus bestätigt keine Zahlung und schließt keinen Bon.
Auch offline, leeres Fach, blockierter Weg, Aufzug/Tür und menschliche Übernahme
gehören in die Hardwareabnahme.

PUDU und KEENON sind erste mögliche Zielhersteller. Ein belastbarer Adapter
benötigt die tatsächlichen Modelle, freigegebenen Hersteller-APIs und Testgeräte.
**Robotik-Endpunkte und fertige Herstellerdriver sind noch nicht implementiert.**

## DATEV, ELSTER und Personal

Finanzbuchhaltung und Payroll werden getrennte Adapter. Für Payroll zuerst
DATEV-Zielprodukt (LODAS / Lohn und Gehalt), Versionsstand, Lohnarten,
Personalnummern und Übergabeverfahren festlegen. Für Finanzen Konten/Steuerschlüssel,
Belegreferenzen, Perioden und Korrekturen festlegen. Exportjournal, Testimport und
Rückmeldung sind Teil der Fertigstellung. Kein generischer JSON-/CSV-Export wird
als fertiger DATEV-Adapter bezeichnet.

ELSTER/ERiC benötigt zugelassene Herstellerkomponenten, Herstellerkennung und
passende Verfahren/Zertifikate. Aktuell erfolgt keine echte Übermittlung.
Arbeitszeit, tariflicher/vertraglicher Zuschlagsanspruch und Steuerbehandlung
bleiben getrennt. Tatsächlich geleistete Zeit wird nicht zwecks Kostenoptimierung
auf andere Mitarbeitende umgebucht. Der vollständige fachliche Stand und offizielle
Referenzen stehen in `PERSONAL_KASSE_SCHNITTSTELLEN.md`.
