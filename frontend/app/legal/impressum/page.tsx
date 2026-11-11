import { connection } from "next/server";
import { LegalPageShell } from "@/components/legal/LegalPageShell";
import { LEGAL } from "@/lib/legal-constants";

export const metadata = { title: "Impressum – FlintPlate" };

export default async function ImpressumPage() {
  await connection();
  const { company, versions } = LEGAL;
  return (
    <LegalPageShell title="Impressum" lastUpdated={versions.impressum}>
      <h2>FlintPlate – ein Produkt von neurofunken</h2>
      <h3>Anbieterangaben gemäß § 5 DDG</h3>
      <p><strong>{company.name}</strong><br />{company.street ?? "Geschäftsanschrift wird ergänzt"}<br />{company.city ?? "Postleitzahl und Ort werden ergänzt"}<br />{company.country}</p>
      <h3>Vertretungsberechtigte Person</h3>
      <p>{company.representedBy ?? "Vollständiger Name und Rechtsform werden ergänzt"}</p>
      <h3>Kontakt</h3>
      <p>{company.email ? <a href={`mailto:${company.email}`}>{company.email}</a> : "Kontaktadresse wird ergänzt"}</p>
      {company.phone && <p>Telefon: {company.phone}</p>}
      {company.vatId && <p>Umsatzsteuer-Identifikationsnummer: {company.vatId}</p>}
      <h3>Register und Verbraucherschlichtung</h3>
      <p>Erforderliche Registerangaben und Angaben nach § 36 VSBG werden nach Bestätigung der Rechtsform und rechtlicher Prüfung ergänzt.</p>
      <h3>Karriereseiten von Unternehmen</h3>
      <p>Unternehmen können ihren eigenen Markenauftritt verwenden. Der technische Anbieter der Plattform ist neurofunken. Arbeitgeber und Verantwortlichkeiten für Bewerbungen müssen auf der jeweiligen Karriereseite eindeutig angegeben werden.</p>
    </LegalPageShell>
  );
}
