"use client";

import { useState } from "react";
import { auth } from "@/lib/auth";
import { coverLetterApi, ApiError, type CoverLetterRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { X, Sparkles, AlertTriangle, Check } from "lucide-react";

interface Props {
  /** Pre-filled from a job card or application */
  initialCompany?: string;
  initialPosition?: string;
  jobId?: string | null;
  applicationId?: string | null;
  jobDescription?: string | null;
  onClose: () => void;
  onGenerated?: (letter: CoverLetterRead) => void;
}

const TONE_OPTIONS = [
  { value: "professionell", label: "Professionell" },
  { value: "modern", label: "Modern & direkt" },
  { value: "kreativ", label: "Kreativ" },
  { value: "konservativ", label: "Konservativ (Sie-Form)" },
];

export function CoverLetterModal({
  initialCompany = "",
  initialPosition = "",
  jobId = null,
  applicationId = null,
  jobDescription = null,
  onClose,
  onGenerated,
}: Props) {
  const [company, setCompany] = useState(initialCompany);
  const [position, setPosition] = useState(initialPosition);
  const [jobDesc, setJobDesc] = useState(jobDescription || "");
  const [companyContext, setCompanyContext] = useState("");
  const [tone, setTone] = useState("professionell");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CoverLetterRead | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    const token = auth.getAccess();
    if (!token) return;
    setGenerating(true);
    setError(null);
    try {
      const letter = await coverLetterApi.generate(token, {
        company,
        position,
        job_id: jobId,
        application_id: applicationId,
        job_description: jobDesc || null,
        company_context: companyContext || null,
        tone,
      });
      setResult(letter);
      onGenerated?.(letter);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Fehler bei der Generierung.");
    } finally {
      setGenerating(false);
    }
  }

  function handleCopy() {
    if (!result) return;
    navigator.clipboard.writeText(result.generated_text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-xl bg-white shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="font-semibold text-gray-900">Anschreiben generieren</h2>
            <p className="text-xs text-gray-400 mt-0.5">KI-Assistent · Sprint 0.6</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={15} /></button>
        </div>

        <div className="p-5 overflow-y-auto max-h-[80vh]">
          {!result ? (
            <form onSubmit={handleGenerate} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="cl-company">Unternehmen *</Label>
                  <Input
                    id="cl-company"
                    required
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    placeholder="Acme GmbH"
                  />
                </div>
                <div>
                  <Label htmlFor="cl-position">Stelle *</Label>
                  <Input
                    id="cl-position"
                    required
                    value={position}
                    onChange={(e) => setPosition(e.target.value)}
                    placeholder="Backend Engineer"
                  />
                </div>
              </div>

              <div>
                <Label htmlFor="cl-desc">Stellenbeschreibung</Label>
                <Textarea
                  id="cl-desc"
                  value={jobDesc}
                  onChange={(e) => setJobDesc(e.target.value)}
                  rows={4}
                  placeholder="Füge die Stellenbeschreibung hier ein…"
                />
              </div>

              <div>
                <Label htmlFor="cl-ctx">Unternehmensinfos (optional)</Label>
                <Textarea
                  id="cl-ctx"
                  value={companyContext}
                  onChange={(e) => setCompanyContext(e.target.value)}
                  rows={2}
                  placeholder="Z.B. Startup, 50 Mitarbeiter, Remote-first…"
                />
              </div>

              <div>
                <Label htmlFor="cl-tone">Ton</Label>
                <select
                  id="cl-tone"
                  value={tone}
                  onChange={(e) => setTone(e.target.value)}
                  className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {TONE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>

              {error && <p className="text-sm text-red-600">{error}</p>}

              <div className="flex justify-end gap-2 pt-1">
                <Button type="button" variant="outline" onClick={onClose}>Abbrechen</Button>
                <Button type="submit" disabled={generating}>
                  {generating ? (
                    <span className="flex items-center gap-2">
                      <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                      Generiere…
                    </span>
                  ) : <><Sparkles size={13} className="inline mr-1" />Generieren</>}
                </Button>
              </div>
            </form>
          ) : (
            <div className="space-y-4">
              {/* AI disclaimer banner */}
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                <AlertTriangle size={12} className="inline mr-1" />KI-generierter Text – bitte sorgfältig prüfen und personalisieren vor dem Versand.
                Modell: <span className="font-mono">{result.model_used}</span>
              </div>

              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-800 whitespace-pre-line leading-relaxed font-mono">
                {result.generated_text}
              </div>

              <div className="flex gap-2 justify-end">
                <Button variant="outline" onClick={() => setResult(null)}>
                  Neu generieren
                </Button>
                <Button onClick={handleCopy}>
                  {copied ? <><Check size={13} className="inline" /> Kopiert!</> : "Kopieren"}
                </Button>
                <Button variant="outline" onClick={onClose}>Schließen</Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
