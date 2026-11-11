import { BRAND } from "./brand";

// Only confirmed operator data belongs here. These server-side settings are
// supplied by the deployment; missing values keep the legal pages in draft.
const value = (input: string | undefined): string | null => input?.trim() || null;

export const LEGAL = {
  reviewed: process.env.LEGAL_REVIEWED === "true" && [process.env.LEGAL_COMPANY_NAME, process.env.LEGAL_REPRESENTED_BY, process.env.LEGAL_STREET, process.env.LEGAL_CITY, process.env.LEGAL_CONTACT_EMAIL, process.env.LEGAL_CONTROLLER_ADDRESS, process.env.LEGAL_PRIVACY_EMAIL].every(v => Boolean(v?.trim())),
  // § 5 DDG – Impressum
  company: {
    name: value(process.env.LEGAL_COMPANY_NAME) ?? BRAND.company,
    /** Vertretungsberechtigte Person(en) und Rechtsform laut verifizierter Betreiberangabe */
    representedBy: value(process.env.LEGAL_REPRESENTED_BY),
    street: value(process.env.LEGAL_STREET),
    city: value(process.env.LEGAL_CITY),
    country: "Deutschland",
    email: value(process.env.LEGAL_CONTACT_EMAIL),
    phone: null as string | null, // optional – wenn vorhanden
    /** Ust-IdNr. oder USt-Nr. – sobald vorhanden */
    vatId: null as string | null,
    /** Berufsrechtliche Regelungen, falls berufsrechtlich reguliert */
    professionalRegs: null as string | null,
  },

  // DSGVO – Datenschutz
  privacy: {
    /** Vollständiger Name des Verantwortlichen (Art. 4 Nr. 7 DSGVO) */
    controllerName: value(process.env.LEGAL_COMPANY_NAME) ?? BRAND.company,
    controllerAddress: value(process.env.LEGAL_CONTROLLER_ADDRESS),
    controllerEmail: value(process.env.LEGAL_PRIVACY_EMAIL),
    /** Datenschutzbeauftragter – nur Pflicht ab 20 DS-Mitarbeitern oder bestimmten Verarbeitungen */
    dpoName: null as string | null,
    dpoEmail: null as string | null,
    /** Aufsichtsbehörde des Bundeslandes, in dem das Unternehmen seinen Sitz hat */
    supervisoryAuthority: null as string | null,
    supervisoryAuthorityUrl: null as string | null,
    /** Google Maps API Key – nur Geocoding, kein Tracking */
    googleMapsNotice: true,
    /** Optional LLM-based CV parser + Job-Matching */
    aiProcessingNotice: true,
    /** Wird E-Mail-Marketing (Newsletter) eingesetzt? */
    emailMarketing: false,
  },

  // Plattform-Flags
  platform: {
    /** Gibt es kostenpflichtige B2C-Tarife (Premium)? → Widerruf-Seite aktivieren */
    hasPaidB2cPlans: false,
    /** B2B AGB aktiv? */
    hasB2bTerms: true,
    /** B2C Nutzungsbedingungen aktiv? */
    hasB2cTerms: true,
  },

  // Versionierung
  versions: {
    impressum: "2026-09-10",
    datenschutz: "2026-09-10",
    agbB2b: "2026-09-10",
    nutzungsbedingungen: "2026-09-10",
  },
} as const;
