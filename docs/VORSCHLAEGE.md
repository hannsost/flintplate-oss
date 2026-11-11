# Vorschläge beim Bestellen

Stand 12.09.2026. Umsetzung in `backend/app/gastro/suggestions.py`, Oberfläche im
Bestellschirm für Service und Gast.

Der Wunsch war „wie bei Amazon oder Netflix", technisch genannt wurde eine
Boltzmann-Maschine. Gebaut ist etwas anderes, und zwar mit Absicht.

## Warum gezählt statt trainiert wird

Ein neuronales Modell braucht viele tausend Vorgänge, bevor es besser rät als eine
Zählung. Ein Restaurant erzeugt am Abend ein paar Dutzend Bons. Was bei den großen
Anbietern tatsächlich den Großteil der Wirkung trägt, ist nicht das Modell, sondern
das gemeinsame Auftreten: Wer A nahm, nahm oft auch B.

Genau das rechnet FlintPlate. Gezählt wird über die Bestellungen der letzten 180
Tage, höchstens 2000 Stück. Zwei Artikel müssen mindestens zweimal zusammen
aufgetaucht sein; eine einzige gemeinsame Bestellung ist Zufall, kein Muster.

Der Grund steht im Klartext neben dem Vorschlag: „In 3 von 3 Bestellungen mit
dieser Auswahl kam das dazu." Das lässt sich nachrechnen, erklären und auch
widerlegen. Ein Modell könnte das nicht.

Fehlt die Historie, kommen die meistbestellten Artikel des Zeitraums, und die
Oberfläche sagt, dass es daran liegt. Kein Vorschlag tut so, als wüsste er mehr,
als in den Daten steht.

## Was nie vorgeschlagen wird

Artikel, die nicht veröffentlicht oder nicht verfügbar sind, und alles, was bereits
im Warenkorb liegt. Vor allem aber: Artikel, die zu den Merkmalen des Gastes nicht
passen. Ein Vorschlag, den jemand nicht essen darf oder nicht essen will, ist kein
Vorschlag. Die Antwort nennt die Zahl der so ausgelassenen Artikel, damit der
Service weiß, dass gefiltert wurde.

In der Kunden-App gilt automatisch das verknüpfte Gastprofil. Im Service lässt sich
ein Gast ausdrücklich mitgeben, dann gilt dessen Profil.

## Wo es erscheint

Im Bestellschirm unter dem Warenkorb, sobald etwas darin liegt, mit höchstens drei
Vorschlägen. Ein Tipp legt den Artikel dazu. Dieselbe Stelle für Service und Gast,
dieselbe Berechnung, unterschiedliche Datenbasis nur durch die Merkmale.

## Geprüft

Sechs HTTP-Tests decken den gemeinsamen Warenkorb, den Rückfall auf die häufigsten
Artikel, die Mindestzahl von zwei gemeinsamen Bestellungen, das Auslassen
unverträglicher Artikel, den Ausschluss ausverkaufter Artikel und den eigenen Weg
der Kunden-App ab. Der Browserdurchlauf `frontend/e2e/flintplate-suggestions.mjs`
legt drei Bestellungen an, wählt danach einen Artikel und bestätigt, dass der
passende Vorschlag samt Begründung erscheint und sich mit einem Tipp übernehmen lässt.

## Noch offen

Es gibt keine Personalisierung über die Merkmale hinaus: die Bestellhistorie eines
einzelnen Gastes fließt nicht ein, obwohl die Daten dafür vorhanden wären. Tageszeit,
Wetter und Saison bleiben unberücksichtigt. Die Zählung läuft bei jeder Anfrage neu
und ist damit an die Größe eines Betriebs gebunden, nicht an die einer Kette.
