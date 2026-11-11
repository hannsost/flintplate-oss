"use client";

import { useState } from "react";
import type { ParseCVResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface ParsedCVPreviewProps {
  result: ParseCVResponse;
  onApply: (data: AppliedData) => void;
}

export interface AppliedData {
  headline?: string;
  location?: string;
  phone?: string;
  skills: Array<{ name: string; level?: string | null; years_of_experience?: number | null }>;
  work_experiences: ParseCVResponse["structured_data"]["work_experiences"];
  educations: ParseCVResponse["structured_data"]["educations"];
}

const CONFIDENCE_LABEL: Record<string, string> = {
  parsed: "KI (GPT-4o)",
  fallback: "Regex-Fallback",
  failed: "Fehlgeschlagen",
};

const CONFIDENCE_COLOR: Record<string, string> = {
  parsed: "bg-green-100 text-green-800",
  fallback: "bg-yellow-100 text-yellow-800",
  failed: "bg-red-100 text-red-800",
};

export function ParsedCVPreview({ result, onApply }: ParsedCVPreviewProps) {
  const sd = result.structured_data;
  const [headline, setHeadline] = useState(sd.headline ?? "");
  const [location, setLocation] = useState(sd.location ?? "");
  const [phone, setPhone] = useState(sd.phone ?? "");
  const [skills, setSkills] = useState(sd.skills ?? []);

  const confidencePct = Math.round(result.confidence * 100);

  function handleApply() {
    onApply({
      headline: headline || undefined,
      location: location || undefined,
      phone: phone || undefined,
      skills,
      work_experiences: sd.work_experiences,
      educations: sd.educations,
    });
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${CONFIDENCE_COLOR[result.parse_status] ?? "bg-gray-100 text-gray-700"}`}>
            {CONFIDENCE_LABEL[result.parse_status] ?? result.parse_status}
          </span>
          <span className="text-xs text-gray-400">
            Konfidenz: {confidencePct}% · {result.token_count} Tokens
          </span>
        </div>
      </div>

      <Separator />

      {/* Editable basic fields */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {sd.name && (
          <div className="sm:col-span-2">
            <p className="text-xs text-gray-400 mb-0.5">Erkannter Name</p>
            <p className="text-sm font-medium text-gray-800">{sd.name}</p>
          </div>
        )}
        <div>
          <Label className="text-xs">Berufsbezeichnung</Label>
          <Input
            value={headline}
            onChange={(e) => setHeadline(e.target.value)}
            placeholder="z.B. Senior Python Engineer"
            className="mt-1 h-8 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">Standort</Label>
          <Input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="z.B. Berlin"
            className="mt-1 h-8 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">Telefon</Label>
          <Input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+49 30 ..."
            className="mt-1 h-8 text-sm"
          />
        </div>
      </div>

      {/* Skills preview */}
      {skills.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-700 mb-2">
            Erkannte Kenntnisse ({skills.length})
          </p>
          <div className="flex flex-wrap gap-1.5">
            {skills.map((s, i) => (
              <div key={i} className="flex items-center gap-1">
                <Badge variant="secondary" className="text-xs">
                  {s.name}
                  {s.level && <span className="ml-1 opacity-60">· {s.level}</span>}
                </Badge>
                <button
                  type="button"
                  onClick={() => setSkills(skills.filter((_, idx) => idx !== i))}
                  className="text-gray-300 hover:text-red-400 text-sm leading-none transition-colors"
                  aria-label={`${s.name} entfernen`}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Work experience preview */}
      {(sd.work_experiences?.length ?? 0) > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-700 mb-2">
            Berufserfahrung ({sd.work_experiences!.length} Einträge)
          </p>
          <ul className="space-y-1">
            {sd.work_experiences!.map((w, i) => (
              <li key={i} className="text-sm text-gray-600">
                <span className="font-medium">{w.title}</span> bei {w.company}
                {w.start_date && <span className="text-gray-400"> · {w.start_date}{w.end_date ? ` – ${w.end_date}` : w.is_current ? " – heute" : ""}</span>}
                {w.source && <span className="ml-1 text-xs text-blue-400">[{w.source}]</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Education preview */}
      {(sd.educations?.length ?? 0) > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-700 mb-2">
            Ausbildung ({sd.educations!.length} Einträge)
          </p>
          <ul className="space-y-1">
            {sd.educations!.map((e, i) => (
              <li key={i} className="text-sm text-gray-600">
                <span className="font-medium">{e.degree ?? "–"}</span>
                {e.field_of_study && ` in ${e.field_of_study}`} · {e.institution}
                {e.source && <span className="ml-1 text-xs text-blue-400">[{e.source}]</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Separator />

      <Button onClick={handleApply} className="w-full">
        Daten ins Profil übernehmen →
      </Button>
    </div>
  );
}
