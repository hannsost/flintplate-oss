"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { JobCreate, JobPosting } from "@/lib/api";
import { normalizeSkills } from "@/lib/skills";

interface Props {
  initial?: Partial<JobPosting>;
  onSubmit: (data: JobCreate) => Promise<void>;
  submitLabel?: string;
}

export function JobForm({ initial, onSubmit, submitLabel = "Speichern" }: Props) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [company, setCompany] = useState(initial?.company ?? "");
  const [location, setLocation] = useState(initial?.location ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [url, setUrl] = useState(initial?.url ?? "");
  const [isRemote, setIsRemote] = useState(initial?.is_remote ?? false);
  const [salaryMin, setSalaryMin] = useState(initial?.salary_min?.toString() ?? "");
  const [salaryMax, setSalaryMax] = useState(initial?.salary_max?.toString() ?? "");
  const [employmentType, setEmploymentType] = useState(initial?.employment_type ?? "");
  const [skillsInput, setSkillsInput] = useState(
    (initial?.required_skills ?? []).join(", ")
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const skills = normalizeSkills(skillsInput.split(","));

    const data: JobCreate = {
      title: title.trim(),
      company: company.trim(),
      location: location.trim() || null,
      description: description.trim() || null,
      url: url.trim() || null,
      is_remote: isRemote,
      salary_min: salaryMin ? parseInt(salaryMin) : null,
      salary_max: salaryMax ? parseInt(salaryMax) : null,
      employment_type: employmentType || null,
      required_skills: skills,
    };

    try {
      await onSubmit(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler beim Speichern.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="title">Stellenbezeichnung *</Label>
          <Input
            id="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="z.B. Senior Backend Engineer"
            required
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="company">Unternehmen *</Label>
          <Input
            id="company"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="Firmenname"
            required
          />
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="location">Standort</Label>
          <Input
            id="location"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="z.B. Berlin, Bayern"
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="employment_type">Beschäftigungsart</Label>
          <select
            id="employment_type"
            value={employmentType}
            onChange={(e) => setEmploymentType(e.target.value)}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">– Bitte wählen –</option>
            <option value="full-time">Vollzeit</option>
            <option value="part-time">Teilzeit</option>
            <option value="contract">Freiberuflich / Projekt</option>
            <option value="internship">Praktikum</option>
          </select>
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="salary_min">Gehalt von (€/Jahr)</Label>
          <Input
            id="salary_min"
            type="number"
            value={salaryMin}
            onChange={(e) => setSalaryMin(e.target.value)}
            placeholder="z.B. 60000"
            min={0}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="salary_max">Gehalt bis (€/Jahr)</Label>
          <Input
            id="salary_max"
            type="number"
            value={salaryMax}
            onChange={(e) => setSalaryMax(e.target.value)}
            placeholder="z.B. 85000"
            min={0}
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="url">Stellenausschreibungs-URL</Label>
        <Input
          id="url"
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://..."
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="skills">Gewünschte Skills (kommagetrennt)</Label>
        <Input
          id="skills"
          value={skillsInput}
          onChange={(e) => setSkillsInput(e.target.value)}
          placeholder="z.B. Python, FastAPI, PostgreSQL, Docker"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="description">Stellenbeschreibung</Label>
        <Textarea
          id="description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Aufgaben, Anforderungen, Benefits…"
          rows={8}
        />
      </div>

      <div className="flex items-center gap-3">
        <input
          id="is_remote"
          type="checkbox"
          checked={isRemote}
          onChange={(e) => setIsRemote(e.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-blue-600"
        />
        <Label htmlFor="is_remote" className="cursor-pointer">
          Remote-Job möglich
        </Label>
      </div>

      <div className="flex justify-end gap-3 pt-2">
        <Button type="submit" disabled={loading}>
          {loading ? "Wird gespeichert…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
