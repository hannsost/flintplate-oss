import { connection } from "next/server";
import { LegalPageShell } from "@/components/legal/LegalPageShell";
import { LEGAL } from "@/lib/legal-constants";

export const metadata = { title: "Nutzungsbedingungen – FlintPlate" };

export default async function NutzungsbedingungenPage() {
  await connection();
  const { company, versions, platform } = LEGAL;

  return (
    <LegalPageShell
      title="Nutzungsbedingungen für Jobsuchende (B2C)"
      lastUpdated={versions.nutzungsbedingungen}
    >
      <p className="text-sm text-gray-500 italic">
        Diese Nutzungsbedingungen gelten für Verbraucher i. S. d. § 13 BGB, die FlintPlate
        als Jobsuchende zur privaten Stellensuche nutzen.
      </p>

      {/* § 1 */}
      <h2>§ 1 Geltungsbereich und Vertragspartner</h2>
      <p>
        (1) Diese Nutzungsbedingungen der <strong>{company.name}</strong>, {company.street},{" "}
        {company.city} (nachfolgend „Anbieter&quot; oder „wir&quot;), gelten für die kostenlose Nutzung
        der Plattform FlintPlate durch Verbraucher (§ 13 BGB) als Jobsuchende.
      </p>
      <p>
        (2) Mit der Registrierung schließen Sie mit uns einen Nutzungsvertrag zu diesen Bedingungen.
      </p>

      {/* § 2 */}
      <h2>§ 2 Leistungen für Jobsuchende</h2>
      <p>Die Plattform bietet Jobsuchenden insbesondere:</p>
      <ul>
        <li>Erstellung und Pflege eines digitalen Bewerberprofils</li>
        <li>Upload und Verwaltung eines Lebenslaufs (CV)</li>
        <li>KI-gestütztes Job-Matching (mit ausdrücklicher Einwilligung)</li>
        <li>KI-gestützter Anschreiben-Generator (mit ausdrücklicher Einwilligung)</li>
        <li>Job-Alarme per E-Mail bei passenden neuen Stellen</li>
        <li>Bewerbungsmanagement und Statusverfolgung</li>
      </ul>
      <p>
        Die Grundnutzung ist kostenlos. {platform.hasPaidB2cPlans
          ? "Kostenpflichtige Premium-Funktionen werden gesondert angeboten; das Widerrufsrecht nach § 355 BGB gilt entsprechend (siehe Widerrufsbelehrung)."
          : "Kostenpflichtige Erweiterungen sind derzeit nicht geplant."}
      </p>

      {/* § 3 */}
      <h2>§ 3 Registrierung und Nutzerkonto</h2>
      <p>
        (1) Zur Nutzung ist eine Registrierung mit einer gültigen E-Mail-Adresse erforderlich.
        Sie sind verpflichtet, wahrheitsgemäße Angaben zu machen.
      </p>
      <p>
        (2) Sie sind mindestens 16 Jahre alt (Art. 8 DSGVO). Jüngere Nutzer benötigen die
        Zustimmung eines Erziehungsberechtigten.
      </p>
      <p>
        (3) Ihre Zugangsdaten sind vertraulich zu halten. Bei Verdacht auf Missbrauch
        informieren Sie uns bitte umgehend unter{" "}
        {company.email ? <a href={`mailto:${company.email}`}>{company.email}</a> : "Kontaktadresse wird ergänzt"}.
      </p>

      {/* § 4 */}
      <h2>§ 4 Einwilligung zur KI-gestützten Verarbeitung</h2>
      <p>
        (1) Die KI-Funktionen (CV-Parser, Job-Matching, Anschreiben-Generator) werden nur
        aktiviert, wenn Sie bei der Registrierung oder in den Einstellungen ausdrücklich
        einwilligen.
      </p>
      <p>
        (2) Die Einwilligung ist freiwillig und hat keinen Einfluss auf die Grundnutzung der
        Plattform. Sie können die Einwilligung jederzeit in Ihren Kontoeinstellungen widerrufen
        (Art. 7 Abs. 3 DSGVO), ohne dass dadurch die Rechtmäßigkeit der bis zum Widerruf
        erfolgten Verarbeitung berührt wird.
      </p>

      {/* § 5 */}
      <h2>§ 5 Pflichten der Nutzerin / des Nutzers</h2>
      <p>Sie verpflichten sich,</p>
      <ul>
        <li>keine falschen Angaben zu machen oder fremde Identitäten zu verwenden,</li>
        <li>keine rechtswidrigen, beleidigenden oder diskriminierenden Inhalte hochzuladen,</li>
        <li>die Plattform nicht für Spam oder automatisierte Massenzugriffe zu nutzen,</li>
        <li>keine Schadsoftware oder schädlichen Skripte einzuspielen.</li>
      </ul>

      {/* § 6 */}
      <h2>§ 6 Sichtbarkeit des Profils</h2>
      <p>
        (1) Ihr Profil ist standardmäßig nur für verifizierte Recruiter auf FlintPlate sichtbar.
        Sie können die Sichtbarkeit in den Einstellungen anpassen.
      </p>
      <p>
        (2) Durch das Anlegen eines öffentlichen Profils erteilen Sie dem Anbieter die
        Erlaubnis, die entsprechenden Informationen an registrierte Recruiter-Nutzer der
        Plattform weiterzugeben.
      </p>

      {/* § 7 */}
      <h2>§ 7 Datenlöschung und Kontobeendigung</h2>
      <p>
        (1) Sie können Ihr Konto jederzeit löschen. Nach der Löschung werden Ihre
        personenbezogenen Daten binnen 30 Tagen entfernt, sofern keine gesetzliche
        Aufbewahrungspflicht entgegensteht.
      </p>
      <p>
        (2) Sie können Ihren Lebenslauf und Ihre Profildaten jederzeit in den Einstellungen
        herunterladen (Datenportabilität nach Art. 20 DSGVO).
      </p>

      {/* § 8 */}
      <h2>§ 8 Haftung des Anbieters</h2>
      <p>
        (1) Der Anbieter haftet unbeschränkt für Schäden aus der Verletzung des Lebens, des
        Körpers oder der Gesundheit sowie für Vorsatz und grobe Fahrlässigkeit.
      </p>
      <p>
        (2) Im Übrigen haftet der Anbieter nur für die Verletzung wesentlicher Vertragspflichten
        (Kardinalspflichten), und zwar begrenzt auf den vorhersehbaren, vertragstypischen Schaden.
      </p>
      <p>
        (3) Für die inhaltliche Richtigkeit von Job-Matching-Ergebnissen und KI-generierten
        Texten übernimmt der Anbieter keine Gewähr; diese Ergebnisse sind als Entscheidungshilfe
        zu verstehen und ersetzen keine eigenständige Prüfung.
      </p>

      {/* § 9 – Widerruf nur wenn hasPaidB2cPlans */}
      {platform.hasPaidB2cPlans && (
        <>
          <h2>§ 9 Widerrufsrecht (kostenpflichtige Dienste)</h2>
          <p>
            Bei kostenpflichtigen Leistungen steht Ihnen als Verbraucher ein Widerrufsrecht
            gemäß §§ 355 ff. BGB zu. Die vollständige Widerrufsbelehrung finden Sie unter{" "}
            <a href="/legal/widerruf">/legal/widerruf</a>.
          </p>
        </>
      )}

      {/* § 9 / 10 */}
      <h2>§ {platform.hasPaidB2cPlans ? "10" : "9"} Änderungen der Nutzungsbedingungen</h2>
      <p>
        (1) Wir behalten uns vor, diese Nutzungsbedingungen zu ändern. Sie werden über
        Änderungen per E-Mail informiert. Die Änderungen gelten als angenommen, wenn Sie
        nicht innerhalb von 30 Tagen nach Bekanntgabe widersprechen und wir in der
        Benachrichtigung auf diese Folge hingewiesen haben.
      </p>
      <p>
        (2) Im Fall eines Widerspruchs sind wir berechtigt, Ihr Konto zum Zeitpunkt des
        Inkrafttretens der neuen Bedingungen zu beenden.
      </p>

      {/* § 10 / 11 */}
      <h2>§ {platform.hasPaidB2cPlans ? "11" : "10"} Schlussbestimmungen</h2>
      <p>
        (1) Es gilt deutsches Recht. Als Verbraucher genießen Sie den Schutz zwingender
        Vorschriften des Staates, in dem Sie Ihren gewöhnlichen Aufenthalt haben.
      </p>
      <p>Die Angaben zur Verbraucherschlichtung nach § 36 VSBG werden vor dem öffentlichen Betrieb rechtlich geprüft und ergänzt.</p>
      <p>
        (3) Sollten einzelne Bestimmungen unwirksam sein, bleibt die Wirksamkeit der übrigen
        Bestimmungen unberührt.
      </p>
    </LegalPageShell>
  );
}
