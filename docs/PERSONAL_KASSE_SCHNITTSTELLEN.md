# Fachliche Umsetzung und Abnahmegrenzen
Stand 11.09.2026. Deutschland als erster Betriebsrahmen; keine automatische
Anwendung deutscher Regeln auf anders konfigurierte Länder.

## Kasse und Nachvollziehbarkeit

Persönliche Mitgliedschaften und zeitlich begrenzte Geräteschlüssel. Service darf
keine Preisentwürfe ändern, keine freien Rabatte vergeben und keine Bons stornieren.
Manager-Aktionen erhalten Akteur, Zeit, Betrieb, betroffenen Datensatz, Revision und
fachliche Begründung im Journal. Wiederholte Order-/Payment-IDs werden überprüft.
Gebuchte Artikel-/Preis-/Steuersnapshots bleiben bei späteren Kartenänderungen erhalten.
Kassenübergabe sperrt weitere Bestelländerungen. Zahlung nur als nachgewiesene
Rückmeldung eines berechtigten Kassenadapters mit korrektem Restbetrag/Währung.

Implementiert und in einer isolierten PostgreSQL-Migrationsprüfung bestätigt:
verkettete Journaleinträge, abgewiesene Änderungen/Löschungen/TRUNCATE sowie
Vorwärts-/Rückwärtsmigration. Ein Exportprüfer kontrolliert die Kette und Felder.

Noch getrennt abnehmen: unabhängige Archivierung/Backups, Kassensturz,
Teil-/Splitzahlungen, Retouren nach Fiskalisierung,
Bargeldschublade, Schichtkassen und TSE-/DSFinV-K-Adapter. Audit-Logs ersetzen keine
Fiskalisierung. Datenbankadministration muss getrennt vom Anwendungsrecht betrieben
werden; auch eine Hashkette ohne unabhängigen Anker ist nicht manipulationssicher
gegen die gesamte Infrastrukturadministration.
[BZSt: DSFinV-K](https://www.bzst.de/DE/Unternehmen/Aussenpruefungen/DigitaleSchnittstelleFinV/digitaleschnittstellefinv_node.html).

## Personal und regelgebundene Planung

Arbeitszeitrecht, Anspruch auf Zuschläge aus Vertrag/Tarif und steuerliche Behandlung
sind getrennte Regelbereiche. Ein steuerfreier Höchstsatz ist kein automatisch
bestehender Zuschlagsanspruch. Tatsächlich geleistete, korrekt zugeordnete Stunden
bilden die Grundlage; Pausen brauchen Lage und Dauer für belastbare Segmentabrechnung.
Nachtarbeit nach Arbeitszeitrecht und steuerliches Nachtzeitfenster sind verschieden.
Regionale Feiertage richten sich nach dem tatsächlichen Arbeitsort.

Erste Prüfungen für Mindestpausen, Tagesdauer und Ruheabstände sind implementiert. Zulässige
Ausnahmen mit Ausgleich brauchen eigene Regeln/Nachweise; keine freie Management-
Checkbox, die gesetzliche Grenzen abschaltet. Wochen-/Ausgleichszeiträume,
Mehrfachbeschäftigung und Berufsschultage müssen im vollständigen Regelwerk ergänzt
und getestet werden. Unbekanntes Alter ist keine Bestätigung der Volljährigkeit.
Für Minderjährige sind Arbeits-/Pausen-/Ruhe-/Schultage separat zu prüfen.
[ArbZG](https://www.gesetze-im-internet.de/arbzg/BJNR117100994.html),
[JArbSchG](https://www.gesetze-im-internet.de/jarbschg/BJNR009650976.html),
[§ 3b EStG](https://www.gesetze-im-internet.de/estg/__3b.html).

Planungsziele: notwendige Stationsqualifikation und Mindestbesetzung zuerst;
danach vorhandene Sollstunden, freiwillig angebotene Verfügbarkeit, Kompetenz,
Kostenprognose, bisherige Verteilung beliebter/unbeliebter Dienste und Überstunden.
Gewichtungen der Leitung sind sichtbar und begründbar. Eine Person darf nicht
aufgrund unbekannter Daten unsichtbar werden; Ausschlussgründe anzeigen. Keine
intransparenten Personenratings aus Kundentexten oder sensiblen Merkmalen.
Steuer-/Kostenplanung simuliert zulässige zukünftige Einsätze; Stunden dürfen nicht
nachträglich auf andere Menschen verschoben werden.

Vertretungssuche fragt nur geeignete freigegebene Personen an. Broadcast oder
Reihenfolge mit Antwortfrist; definitive Annahme prüft Regeln erneut und übernimmt
atomar genau eine Person. Überholte Angebote erlöschen. Zustellung/Öffnung/Antwort
getrennt protokollieren. In-App-Angebote sind keine versandte Push/SMS/Telefonanfrage;
externe Kanäle benötigen eingerichtete, freigegebene Provider und Opt-in.

## DATEV und ELSTER

DATEV bietet für Payroll ASCII-Dateischnittstellen und gesonderte Datenservices.
Die aktuelle Zielversion und das DATEV-Produkt (LODAS oder Lohn und Gehalt) bestimmen
Dateiaufbau, Stammdaten-/Bewegungsdaten und Lohnartenmapping. Ein eigener Export
wird zunächst als fachlicher Prüfexport bezeichnet; erst erfolgreicher Zielimport
macht daraus einen überprüften DATEV-Adapter. API-Datenservices erfordern die
passenden Voraussetzungen/Partnerimplementierung. Finanzbuchhaltung und Payroll
sind eigenständige Schnittstellen.
[DATEV Payroll-Schnittstellen](https://www.datev.de/web/de/unternehmen/loesungen/lohn-und-personal/lohn-und-gehaltsabrechnung/schnittstellen),
[aktuelle DATEV-Schnittstellenänderungen](https://developer.datev.de/en/news/details/shssmh53tmdmu4qsdu6g4hk0).

ELSTER verwendet unter anderem die ERiC-C-Bibliothek für Plausibilisierung und
Übertragung. Herstellerregistrierung, Entwicklerzugang und Hersteller-ID sind
notwendige externe Schritte. Zertifikate und reale Steuerübertragungen gehören
nicht in Demo-Daten; es gibt hier noch keine erfolgte ELSTER-Abgabe.
[ELSTER Entwickler](https://www.elster.de/eportal/infoseite/entwickler?locale=de_DE).

## Robotik

Herstellerneutrale fachliche Aufgaben: Lieferung an freigegebenen Zielpunkt,
Abräumfahrt, Abholung an Küchenstation, Status-/Fehlerrückmeldung. Physische Bewegung,
Hinderniserkennung, Not-Aus und sichere Trajektorien verbleiben in den jeweiligen
zertifizierten Geräte-/Herstellersystemen. Ein veralteter Bon oder eine wiederholte
Netzantwort darf keine zweite Fahrt/Produktion auslösen. Abgebrochene Jobs werden
nicht still erneut gesendet. Keine generische Schnittstelle als getestete
Kompatibilität zu sämtlichen Koch- oder Servicerobotern bewerben.

PUDU stellt Open-Platform-/Cloud-/Private-Cloud-/OS-SDK-Wege dar; KEENON eine
Entwicklungsplattform für seine Geräte. Konkrete Freigaben, Modelle, Fähigkeiten und
Kontoverträge müssen für jeden Adapter geprüft werden. Eine Herstellerintegration
wird erst mit dem jeweiligen Testgerät abgenommen.
[PUDU Open Platform](https://open.pudutech.com/en),
[KEENON Plattform](https://www.robotkeenon.com/).
