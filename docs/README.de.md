# FlintPlate

Gastrosoftware von neurofunken, aufgebaut auf der Palmscout-Personalplattform.

Lokal: [Betriebsoberfläche](http://localhost:3012/gastro) ·
[Team-App](http://localhost:3012/team) · [API](http://localhost:8012/docs).

Implementierter Kern: veröffentlichte Speisekarte mit Preisständen, Bestellungen und
Küchenablauf, Stockwerke/Räume, Tische und Aktivitäten mit Zeitabrechnung,
Reservierungen, To-go-Verpackung/Pfand, Gutscheine/Rabatte/Punkte, Dienstplanung,
persönliche Team-/Gast-PWAs, Gerätezugänge, FireFlint-Managementadapter und
Vertretungssuche mit Eignung, Freiwilligkeit, Fristen und verbindlicher Zusage.
Für Reservierungen schlägt die Entscheidungsebene drei begründete Tischoptionen vor;
harte Regeln bleiben bindend, siehe [KI-Entscheidungen](KI-ENTSCHEIDUNGEN.md).
Qualifikationen pflegt das Team über [Profilvorlagen](PROFILVORLAGEN.md) mit
sichtbarer Herkunft je Feld; Rolle und freiwillige Bereitschaft bleiben persönlich.
Gäste bestellen nach Freigabe auch an den Tisch und fordern die Zahlung mit
Trinkgeld im Handy an; verteilt wird nach einer sichtbaren Regel, siehe
[Tischbestellung und Trinkgeld](TISCHBESTELLUNG_UND_TRINKGELD.md).
Kunden-App, Team-App und Betriebsoberfläche halten sich selbst aktuell und zeigen
Wartezeiten statt bloßer Zustände, siehe [Was von selbst passiert](LIVE_BEDIENUNG.md).
Stammgäste hält das [Kundenbuch](KUNDENBUCH.md) fest, mit Einwilligung für
Gesundheitshinweise, Ablauffristen und protokolliertem Zugriff.
Zutatenlisten am Tisch und die Reaktion auf Allergien, Diäten und Zustände
beschreibt [Zutaten und Merkmale](ZUTATEN_UND_MERKMALE.md); nur Alkohol an
Minderjährige ist eine echte Sperre, alles andere warnt und kann bestätigt werden.
Beim Bestellen schlägt FlintPlate passende Artikel aus dem gemeinsamen Auftreten
früherer Bons vor, mit nachrechenbarer Begründung: [Vorschläge](VORSCHLAEGE.md).
Für Absprachen während der Schicht gibt es den [Team-Chat](TEAM_CHAT.md) in
Betriebsoberfläche und Team-App, mit Ablauffrist je Nachricht.

Das Entwicklungsprodukt ist noch keine vollständig abgenommene Kassen-/Lohnlösung.
Es ist kein Zahlungsanbieter angebunden; FlintPlate bucht kein Geld ab.
Native Store-Apps, konkrete Hardware-/Roboteradapter, DATEV/ELSTER, Fiskalisierung,
vollständige Zuschlags-/Jugendschutzregeln und der FireFlint-Editorrückkanal bleiben
weitere Arbeit. Die lokalen Assistenzhinweise sind regelbasiert.

Start und Demozugänge: [Lokaler Betrieb](LOKALER_BETRIEB.md).
FlintPlate erhält eigene lokale Dienste und eigene Datenbanken. Bestehende
Palmscout- oder FireFlint-Datenbanken dürfen nicht für Entwicklungstests verwendet werden.
