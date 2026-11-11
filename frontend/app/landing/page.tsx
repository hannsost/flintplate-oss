"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

const FEATURES = [
  { icon: "🤖", title: "KI-CV-Parser", desc: "Lade deinen Lebenslauf hoch. Unsere KI extrahiert alle Daten automatisch." },
  { icon: "🎯", title: "Job-Matching", desc: "Wir finden die passenden Stellen mit einem KI-Score basierend auf deinem Profil." },
  { icon: "📋", title: "Bewerbungs-Tracker", desc: "Verfolge alle deine Bewerbungen im Kanban-Board – von Recherche bis Angebot." },
  { icon: "✍️", title: "KI-Anschreiben", desc: "Generiere personalisierte Anschreiben in Sekunden. Mit DSGVO-Kennzeichnung." },
  { icon: "🎤", title: "Interview-Vorbereitung", desc: "KI-generierte Interviewfragen + STAR-Methoden-Coach für dein nächstes Gespräch." },
  { icon: "📄", title: "CV-Export", desc: "Exportiere dein Profil als PDF, DOCX oder LinkedIn-Text." },
];

export default function LandingPage() {
  const [email, setEmail] = useState("");
  const [joined, setJoined] = useState(false);

  function handleWaitlist(e: React.FormEvent) {
    e.preventDefault();
    // In production this would call a waitlist API
    setJoined(true);
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      {/* Navbar */}
      <header className="sticky top-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <span className="text-lg font-bold tracking-tight text-blue-600">
            palm<span className="text-gray-900">scout</span>
          </span>
          <div className="flex items-center gap-3 text-sm">
            <Link href="/login" className="text-gray-600 hover:text-gray-900 transition-colors">
              Anmelden
            </Link>
            <Link href="/register">
              <Button size="sm">Kostenlos starten</Button>
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-4xl px-4 py-20 text-center">
        <Badge variant="secondary" className="mb-4 text-xs">
          🚀 Beta · Sprint 0.8
        </Badge>
        <h1 className="text-4xl sm:text-5xl font-bold text-gray-900 leading-tight mb-4">
          Deine KI-gestützte{" "}
          <span className="text-blue-600">Bewerbungsplattform</span>
        </h1>
        <p className="text-lg text-gray-500 max-w-2xl mx-auto mb-8">
          Vom CV-Upload bis zum Angebot: FlintPlate unterstützt dich mit KI bei jedem Schritt
          deiner Jobsuche. Kostenlos, DSGVO-konform, made in Germany.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link href="/register">
            <Button size="lg" className="px-8">Jetzt kostenlos starten →</Button>
          </Link>
          <Link href="/register/recruiter">
            <Button variant="outline" size="lg" className="border-blue-300 text-blue-700 hover:bg-blue-50">
              Recruiter-Zugang →
            </Button>
          </Link>
        </div>
        <p className="mt-4 text-sm text-gray-400">
          Kandidat? Klicke auf &quot;Kostenlos starten&quot; · Recruiter? Klicke auf &quot;Recruiter-Zugang&quot;
        </p>
      </section>

      {/* Features grid */}
      <section className="mx-auto max-w-5xl px-4 py-16">
        <h2 className="text-2xl font-bold text-gray-900 text-center mb-10">
          Alles was du für deine Jobsuche brauchst
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-md transition-shadow">
              <div className="text-3xl mb-3">{f.icon}</div>
              <h3 className="font-semibold text-gray-900 mb-1">{f.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Social proof */}
      <section className="bg-blue-600 py-12">
        <div className="mx-auto max-w-3xl px-4 text-center">
          <p className="text-blue-100 text-sm font-medium mb-2">PHASE 0 · BETA</p>
          <h2 className="text-2xl font-bold text-white mb-2">Sei unter den ersten 100 Beta-Testern</h2>
          <p className="text-blue-200 mb-6 text-sm">
            Kostenloser Zugang · Direkter Einfluss auf Produktentscheidungen · Founding-Member-Badge
          </p>

          {joined ? (
            <div className="rounded-xl bg-white/20 px-6 py-4 text-white">
              🎉 Du bist auf der Warteliste! Wir melden uns in Kürze.
            </div>
          ) : (
            <form onSubmit={handleWaitlist} className="flex flex-col sm:flex-row gap-3 max-w-md mx-auto">
              <Input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="deine@email.de"
                className="bg-white border-0"
              />
              <Button type="submit" variant="secondary" className="shrink-0">
                Warteliste beitreten
              </Button>
            </form>
          )}
        </div>
      </section>

      {/* Trust badges */}
      <section className="mx-auto max-w-3xl px-4 py-12 text-center">
        <div className="flex flex-wrap justify-center gap-6 text-sm text-gray-400">
          <span>🇩🇪 Hosting in Deutschland</span>
          <span>🔒 DSGVO-konform</span>
          <span>🤖 KI-Outputs gekennzeichnet</span>
          <span>🆓 Kostenlos in der Beta</span>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-200 bg-white px-0 pt-6 pb-24 sm:pb-6">
        <div className="mx-auto max-w-5xl px-4 flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
          <span className="text-sm font-semibold tracking-tight">
            palm<span className="text-blue-600">scout</span>
            <span className="ml-2 text-xs font-normal text-gray-400">© {new Date().getFullYear()} neurofunken</span>
          </span>
          <nav className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1 text-xs text-gray-500">
            <Link href="/legal/impressum" className="hover:text-gray-800 transition-colors">Impressum</Link>
            <Link href="/legal/datenschutz" className="hover:text-gray-800 transition-colors">Datenschutz</Link>
            <Link href="/legal/agb-b2b" className="hover:text-gray-800 transition-colors">AGB (Unternehmen)</Link>
            <Link href="/legal/nutzungsbedingungen" className="hover:text-gray-800 transition-colors">Nutzungsbedingungen</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
