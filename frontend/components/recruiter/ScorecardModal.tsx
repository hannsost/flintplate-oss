"use client";

import { useRef } from "react";
import { Button } from "@/components/ui/button";
import { Printer } from "lucide-react";
import type { RecruiterApplication, CandidateMatch } from "@/lib/api";

interface Props {
  application?: RecruiterApplication | null;
  candidate?: CandidateMatch | null;
  recruiterName: string;
  jobTitle: string;
  companyName: string;
  onClose: () => void;
}

export function ScorecardModal({
  application,
  candidate,
  recruiterName,
  jobTitle,
  companyName,
  onClose,
}: Props) {
  const printRef = useRef<HTMLDivElement>(null);

  function handlePrint() {
    const content = printRef.current?.innerHTML;
    if (!content) return;
    const win = window.open("", "_blank", "width=800,height=600");
    if (!win) return;
    win.document.write(`<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Kandidaten-Scorecard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; padding: 40px; color: #111; }
    .sc-header { border-bottom: 2px solid #2563eb; padding-bottom: 16px; margin-bottom: 24px; }
    .sc-brand { font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: .05em; }
    .sc-title { font-size: 22px; font-weight: 700; margin: 6px 0 2px; }
    .sc-sub { font-size: 14px; color: #4b5563; }
    .sc-section { margin-top: 20px; }
    .sc-section-label { font-size: 10px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; }
    .sc-info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .sc-info-item { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 10px 14px; }
    .sc-info-key { font-size: 10px; color: #9ca3af; }
    .sc-info-val { font-size: 14px; font-weight: 500; color: #111; margin-top: 2px; }
    .sc-skills { display: flex; flex-wrap: wrap; gap: 6px; }
    .sc-skill { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; border-radius: 20px; font-size: 11px; padding: 3px 10px; }
    .sc-score { display: inline-flex; align-items: center; justify-content: center; width: 56px; height: 56px; border-radius: 50%; border: 3px solid #2563eb; font-size: 18px; font-weight: 700; color: #2563eb; }
    .sc-footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 10px; color: #9ca3af; display: flex; justify-content: space-between; }
    @media print { body { padding: 20px; } }
  </style>
</head>
<body>${content}</body>
</html>`);
    win.document.close();
    win.focus();
    win.print();
  }

  const name = application?.candidate_name ?? candidate?.full_name ?? "Kandidat";
  const headline = application?.candidate_headline ?? candidate?.headline ?? null;
  const location = application?.candidate_location ?? candidate?.location ?? null;
  const skills = candidate?.matched_skills ?? [];
  const score = candidate?.score ?? null;
  const today = new Date().toLocaleDateString("de-DE", { day: "2-digit", month: "long", year: "numeric" });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl overflow-hidden">
        {/* Modal header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="font-semibold text-gray-900">White-Label Scorecard</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {/* Printable content */}
        <div className="p-6">
          <div ref={printRef}>
            <div className="sc-header" style={{ borderBottom: "2px solid #2563eb", paddingBottom: "16px", marginBottom: "24px" }}>
              <p className="sc-brand text-[11px] font-semibold uppercase tracking-widest text-gray-400 mb-1">
                {recruiterName} · Kandidaten-Scorecard
              </p>
              <p className="sc-title text-2xl font-bold text-gray-900">{name}</p>
              {headline && <p className="sc-sub text-sm text-gray-500 mt-1">{headline}</p>}
            </div>

            {/* Info grid */}
            <div className="sc-section mb-5">
              <p className="sc-section-label text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-2">
                Position
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                  <p className="text-[10px] text-gray-400">Stelle</p>
                  <p className="text-sm font-medium text-gray-900 mt-0.5">{jobTitle}</p>
                </div>
                <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                  <p className="text-[10px] text-gray-400">Unternehmen</p>
                  <p className="text-sm font-medium text-gray-900 mt-0.5">{companyName}</p>
                </div>
                {location && (
                  <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                    <p className="text-[10px] text-gray-400">Standort</p>
                    <p className="text-sm font-medium text-gray-900 mt-0.5">{location}</p>
                  </div>
                )}
                {score != null && (
                  <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 flex items-center gap-3">
                    <div className="flex items-center justify-center w-12 h-12 rounded-full border-2 border-blue-600 text-blue-700 font-bold text-lg shrink-0">
                      {Math.round(score * 100)}
                    </div>
                    <div>
                      <p className="text-[10px] text-blue-400">Match-Score</p>
                      <p className="text-sm font-medium text-blue-800 mt-0.5">
                        {score >= 0.8 ? "Sehr gut" : score >= 0.6 ? "Gut" : "Ausreichend"}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Skills */}
            {skills.length > 0 && (
              <div className="sc-section mb-5">
                <p className="sc-section-label text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-2">
                  Skills
                </p>
                <div className="flex flex-wrap gap-2">
                  {skills.map((s: string) => (
                    <span
                      key={s}
                      className="rounded-full border border-blue-200 bg-blue-50 px-3 py-0.5 text-xs font-medium text-blue-700"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Footer */}
            <div className="mt-8 pt-4 border-t border-gray-100 flex items-center justify-between text-[10px] text-gray-400">
              <span>Erstellt am {today} · {recruiterName}</span>
              <span>FlintPlate Recruiting Platform</span>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 border-t border-gray-100 px-5 py-4">
          <Button type="button" variant="outline" onClick={onClose}>
            Schließen
          </Button>
          <Button type="button" onClick={handlePrint}>
            <Printer size={14} className="inline mr-1" />Drucken / Als PDF speichern
          </Button>
        </div>
      </div>
    </div>
  );
}
