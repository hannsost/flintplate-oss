import { connection } from "next/server";
import { LegalPageShell } from "@/components/legal/LegalPageShell";
import { LEGAL } from "@/lib/legal-constants";

export const metadata = { title: "AGB für Unternehmen – FlintPlate" };

export default async function AgbB2bPage() {
  await connection();
  const { company, versions } = LEGAL;

  return (
    <LegalPageShell
      title="Allgemeine Geschäftsbedingungen für Unternehmenskunden (B2B)"
      lastUpdated={versions.agbB2b}
    >
      <p className="text-sm text-gray-500 italic">
        Diese AGB gelten ausschließlich für Unternehmer i. S. d. § 14 BGB (Recruitingagenturen,
        Personaldienstleister, Unternehmen) bei der gewerblichen Nutzung der FlintPlate-Plattform.
      </p>

      {/* § 1 */}
      <h2>§ 1 Geltungsbereich</h2>
      <p>
        (1) Diese Allgemeinen Geschäftsbedingungen (AGB) der <strong>{company.name}</strong>
        {" "}(nachfolgend „Anbieter&quot;) gelten für alle Verträge, die Unternehmer (§ 14 BGB) über
        die Nutzung der Plattform FlintPlate auf der vertraglich vereinbarten Produktdomain abschließen.
      </p>
      <p>
        (2) Abweichende, entgegenstehende oder ergänzende AGB des Kunden gelten nur, wenn der
        Anbieter ihrer Geltung ausdrücklich schriftlich zugestimmt hat.
      </p>

      {/* § 2 */}
      <h2>§ 2 Leistungsbeschreibung</h2>
      <p>
        (1) FlintPlate ist eine cloudbasierte Recruiting-Plattform (SaaS), die Recruiting-
        und Personalvermittlungsprozesse digital unterstützt. Sie umfasst insbesondere:
      </p>
      <ul>
        <li>Verwaltung von Stellenanzeigen und Bewerberpipelines</li>
        <li>KI-gestützte Kandidatenprofilanalyse (CV-Parser, Job-Matching)</li>
        <li>Dokumentenmanagement und E-Signaturfunktionen</li>
        <li>Zeitarbeitsverwaltung (Disposition, Einsatzplanung)</li>
        <li>Provisionsabrechnung und Organisationsstrukturverwaltung</li>
        <li>Weitere Funktionen gemäß dem jeweils aktuellen Feature-Set der Plattform</li>
      </ul>
      <p>
        (2) Der Anbieter ist berechtigt, den Leistungsumfang zu erweitern, anzupassen oder
        einzustellen, sofern dies dem Kunden mit angemessener Vorlauffrist mitgeteilt wird.
      </p>

      {/* § 3 */}
      <h2>§ 3 Registrierung und Zugangsdaten</h2>
      <p>
        (1) Zur Nutzung der Plattform ist eine Registrierung erforderlich. Der Kunde hat
        zutreffende und vollständige Angaben zu machen und diese aktuell zu halten.
      </p>
      <p>
        (2) Zugangsdaten sind vertraulich zu behandeln. Der Kunde haftet für alle Handlungen,
        die unter seinen Zugangsdaten vorgenommen werden, es sei denn, er hat den Missbrauch
        nicht zu vertreten.
      </p>

      {/* § 4 */}
      <h2>§ 4 Pflichten des Kunden</h2>
      <p>Der Kunde verpflichtet sich:</p>
      <ul>
        <li>
          Die Plattform ausschließlich für rechtmäßige Zwecke zu nutzen und keine Inhalte
          hochzuladen, die gegen geltendes Recht, Rechte Dritter oder die guten Sitten verstoßen.
        </li>
        <li>
          Datenschutzrechtliche Pflichten gegenüber Bewerbern und Mitarbeitern eigenverantwortlich
          einzuhalten. Soweit der Kunde personenbezogene Daten Dritter über die Plattform
          verarbeitet, ist er alleiniger datenschutzrechtlicher Verantwortlicher; ein AVV ist
          separat abzuschließen.
        </li>
        <li>
          Die Plattform nicht in einer Weise zu nutzen, die die Integrität, Verfügbarkeit oder
          Sicherheit der Systeme gefährdet.
        </li>
        <li>
          Den Anbieter unverzüglich über Sicherheitsvorfälle oder Missbrauch in Kenntnis zu setzen.
        </li>
      </ul>

      {/* § 5 */}
      <h2>§ 5 Verfügbarkeit und Wartung</h2>
      <p>
        (1) Der Anbieter strebt eine Verfügbarkeit der Plattform von 99 % im Jahresmittel an,
        ausgenommen geplante Wartungsarbeiten, die nach Möglichkeit außerhalb der Hauptnutzungszeiten
        (Montag–Freitag, 08–20 Uhr MEZ) durchgeführt werden.
      </p>
      <p>
        (2) Der Anbieter haftet nicht für Ausfälle, die durch höhere Gewalt, Handlungen Dritter
        oder Umstände außerhalb seines Einflussbereichs verursacht werden.
      </p>

      {/* § 6 */}
      <h2>§ 6 Entgelte und Zahlungsbedingungen</h2>
      <p>
        (1) Die Nutzung der Basisversion ist derzeit kostenlos. Kostenpflichtige Erweiterungen
        werden separat vereinbart und schriftlich bestätigt.
      </p>
      <p>
        (2) Alle angegebenen Preise verstehen sich als Nettopreise zzgl. der gesetzlichen
        Umsatzsteuer.
      </p>
      <p>
        (3) Rechnungen sind innerhalb von 14 Tagen ab Rechnungsdatum ohne Abzug zu begleichen,
        sofern nichts anderes vereinbart ist.
      </p>

      {/* § 7 */}
      <h2>§ 7 Datenschutz und Auftragsverarbeitung</h2>
      <p>
        (1) Soweit der Kunde personenbezogene Daten von Bewerbern oder Mitarbeitern über die
        Plattform verarbeitet, ist der Abschluss eines Auftragsverarbeitungsvertrags (AVV)
        gemäß Art. 28 DSGVO erforderlich.
      </p>
      <p>
        (2) Muster-AVV und weitere Datenschutzinformationen sind auf Anfrage bei{" "}
        {company.email ? <a href={`mailto:${company.email}`}>{company.email}</a> : "Kontaktadresse wird ergänzt"} erhältlich.
      </p>

      {/* § 8 */}
      <h2>§ 8 Geistiges Eigentum</h2>
      <p>
        (1) Die Plattform, ihr Code, ihre Gestaltung und sämtliche Inhalte des Anbieters sind
        urheberrechtlich geschützt. Der Kunde erhält ein nicht ausschließliches, nicht
        übertragbares Recht zur Nutzung der Plattform im Rahmen dieser AGB.
      </p>
      <p>
        (2) Der Kunde räumt dem Anbieter eine nicht exklusive, kostenfreie Lizenz an den von
        ihm hochgeladenen Inhalten ein, soweit dies für die Erbringung der Leistungen erforderlich
        ist. Eine darüberhinausgehende Nutzung findet nicht statt.
      </p>

      {/* § 9 */}
      <h2>§ 9 Haftungsbeschränkung</h2>
      <p>
        (1) Der Anbieter haftet für Schäden aus der Verletzung des Lebens, des Körpers oder der
        Gesundheit sowie für vorsätzliche und grob fahrlässige Pflichtverletzungen unbeschränkt.
      </p>
      <p>
        (2) Bei leicht fahrlässiger Verletzung wesentlicher Vertragspflichten (Kardinalspflichten)
        ist die Haftung auf den vorhersehbaren, vertragstypischen Schaden begrenzt.
      </p>
      <p>
        (3) Im Übrigen ist die Haftung des Anbieters ausgeschlossen. Dies gilt insbesondere für
        Datenverluste, entgangenen Gewinn und mittelbare Schäden.
      </p>

      {/* § 10 */}
      <h2>§ 10 Laufzeit und Kündigung</h2>
      <p>
        (1) Der Vertrag läuft auf unbestimmte Zeit und kann von beiden Parteien jederzeit mit
        einer Frist von 30 Tagen zum Monatsende gekündigt werden, sofern keine abweichende
        Laufzeit vereinbart ist.
      </p>
      <p>
        (2) Das Recht zur außerordentlichen Kündigung aus wichtigem Grund bleibt unberührt.
        Ein wichtiger Grund liegt insbesondere vor, wenn der Kunde gegen wesentliche Pflichten
        aus diesen AGB verstößt.
      </p>
      <p>
        (3) Nach Beendigung des Vertrags kann der Kunde seine Daten innerhalb von 30 Tagen
        exportieren. Danach werden alle Kundendaten gelöscht, sofern keine gesetzlichen
        Aufbewahrungspflichten entgegenstehen.
      </p>

      {/* § 11 */}
      <h2>§ 11 Änderungen der AGB</h2>
      <p>
        (1) Der Anbieter behält sich vor, diese AGB mit einer Ankündigungsfrist von mindestens
        30 Tagen zu ändern. Die Änderungen werden dem Kunden per E-Mail oder über die Plattform
        mitgeteilt.
      </p>
      <p>
        (2) Widerspricht der Kunde der Änderung nicht innerhalb von 30 Tagen, gelten die
        geänderten AGB als angenommen. Der Anbieter wird im Änderungshinweis auf diese Folge
        ausdrücklich hinweisen.
      </p>

      {/* § 12 */}
      <h2>§ 12 Schlussbestimmungen</h2>
      <p>
        (1) Es gilt ausschließlich deutsches Recht unter Ausschluss des UN-Kaufrechts (CISG).
      </p>
      <p>
        (2) Ausschließlicher Gerichtsstand für alle Streitigkeiten aus diesem Vertrag ist
        der Sitz des Anbieters, sofern der Kunde Kaufmann, juristische Person des öffentlichen
        Rechts oder öffentlich-rechtliches Sondervermögen ist.
      </p>
      <p>
        (3) Sollten einzelne Bestimmungen dieser AGB unwirksam sein oder werden, bleibt die
        Wirksamkeit der übrigen Bestimmungen unberührt.
      </p>
    </LegalPageShell>
  );
}
