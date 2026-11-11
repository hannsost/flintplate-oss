import { connection } from "next/server";
import { LegalPageShell } from "@/components/legal/LegalPageShell";
import { LEGAL } from "@/lib/legal-constants";

export const metadata = { title: "Datenschutz – FlintPlate" };

export default async function DatenschutzPage() {
  await connection();
  const { privacy, versions } = LEGAL;
  return (
    <LegalPageShell title="Datenschutzinformationen" lastUpdated={versions.datenschutz}>
      <h2>Verantwortlicher und Kontakt</h2>
      <p>{privacy.controllerName ?? "wird ergänzt"}<br />{privacy.controllerAddress ?? "Vollständige Anschrift wird ergänzt"}<br />{privacy.controllerEmail ? <a href={`mailto:${privacy.controllerEmail}`}>{privacy.controllerEmail}</a> : "Datenschutzkontakt wird ergänzt"}</p>
      <h2>Verarbeitungen in FlintPlate</h2>
      <p>FlintPlate unterstützt Nutzerkonten, Reservierungen, Bestellungen, Gästebuch, Kommunikation sowie Personalverwaltung und Einsatzplanung. Dabei können Gast-, Kontakt-, Bestell-, Profil- und Beschäftigungsdaten verarbeitet werden.</p>
      <p>Vor dem öffentlichen Betrieb müssen für jede Verarbeitung Zweck, Rechtsgrundlage, Empfänger und Speicherdauer festgelegt werden. Für Beschäftigtendaten sind insbesondere § 26 BDSG sowie Artikel 6 und gegebenenfalls Artikel 9 DSGVO zu prüfen. Eine Auftragsverarbeitungsvereinbarung regelt Pflichten zwischen Auftraggeber und Dienstleister; sie ersetzt keine Rechtsgrundlage für die Verarbeitung.</p>
      <h2>Arbeitgeber und Partnerunternehmen</h2>
      <p>Arbeitgeber entscheiden über ihre Bewerbungs- und Personalprozesse. Die Rollen von neurofunken und dem jeweiligen Unternehmen sowie erforderliche Vereinbarungen zur Auftragsverarbeitung oder gemeinsamen Verantwortlichkeit müssen für den konkreten Einsatz bestimmt werden. Eine Zusammenarbeit zwischen Unternehmen berechtigt nicht automatisch zur Weitergabe von Bewerberprofilen.</p>
      <h2>KI-Unterstützung</h2>
      <p>KI-Funktionen müssen vor ihrer Nutzung erkennen lassen, welche Daten zu welchem Zweck verarbeitet werden. Soweit eine Funktion auf Einwilligung beruht, muss diese freiwillig und widerrufbar sein. Ein Widerruf wirkt für die Zukunft. KI-Ergebnisse können fehlerhaft sein und erfordern eine sachkundige Prüfung.</p>
      <p>Der eingesetzte Dienstleister, Verarbeitungsregionen, Unterauftragnehmer und etwaige Drittlandtransfers werden vor Freigabe der jeweiligen Integration dokumentiert. Eine menschliche Bestätigung allein hebt die Anforderungen an automatisierte Entscheidungen und KI-Systeme im Beschäftigungsbereich nicht auf.</p>
      <h2>Hosting, E-Mail, Kalender und Karten</h2>
      <p>Hostingstandorte, Dienstleisterverträge, Zugriffsschutz und Löschfristen sind für den produktiven Betrieb noch zu bestätigen. Externe E-Mail-, Kalender- und Kartendienste werden gesondert geprüft. Bei Verbindungen zu solchen Diensten können Daten an deren Betreiber übermittelt werden.</p>
      <h2>Speicherung im Browser</h2>
      <p>Zur Anmeldung werden Zugangsdaten für die Sitzung im lokalen Browserspeicher gehalten. Oberflächeneinstellungen werden ebenfalls lokal gespeichert. Beim Abmelden entfernt FlintPlate die Sitzungstoken. Die endgültigen Informationen zu technisch erforderlichen Speichern und optionalen Diensten werden anhand der freigegebenen Bereitstellung ergänzt.</p>
      <h2>Ihre Rechte</h2>
      <p>Nach Maßgabe der DSGVO bestehen Rechte auf Auskunft, Berichtigung, Löschung, Einschränkung, Datenübertragbarkeit und Widerspruch sowie auf Widerruf einer Einwilligung. Sie können sich bei einer Datenschutzaufsichtsbehörde beschweren. Zuständige Kontakte und das verbindliche Verfahren zur Bearbeitung von Anfragen werden vor dem öffentlichen Betrieb angegeben.</p>
      <p>Diese Entwicklungsfassung ist noch keine vollständige Information nach Artikeln 13 und 14 DSGVO.</p>
    </LegalPageShell>
  );
}
