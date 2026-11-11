"use client";

import { useState } from "react";
import { auth } from "@/lib/auth";
import { interviewScheduleApi, ApiError } from "@/lib/api";
import type { InterviewScheduleRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  applicationId: string;
  candidateName: string | null;
  onClose: () => void;
  onSuccess: (schedule: InterviewScheduleRead) => void;
}

export function InterviewModal({ applicationId, candidateName, onClose, onSuccess }: Props) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("10:00");
  const [meetingUrl, setMeetingUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!date || !time) { setError("Bitte Datum und Uhrzeit angeben."); return; }

    const token = auth.getAccess();
    if (!token) return;

    // Build ISO datetime with local timezone offset
    const localDt = new Date(`${date}T${time}:00`);
    if (isNaN(localDt.getTime())) { setError("Ungültiges Datum."); return; }

    setLoading(true);
    setError(null);
    try {
      const schedule = await interviewScheduleApi.propose(token, applicationId, {
        scheduled_at: localDt.toISOString(),
        meeting_url: meetingUrl.trim() || null,
        notes: notes.trim() || null,
      });
      onSuccess(schedule);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Fehler beim Erstellen des Termins.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="font-semibold text-gray-900">Interview planen</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {candidateName && (
            <p className="text-sm text-gray-600">
              Kandidat: <span className="font-medium">{candidateName}</span>
            </p>
          )}

          {error && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="int-date">Datum *</Label>
              <Input
                id="int-date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                min={new Date().toISOString().slice(0, 10)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="int-time">Uhrzeit *</Label>
              <Input
                id="int-time"
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="int-url">Meeting-Link (optional)</Label>
            <Input
              id="int-url"
              type="url"
              value={meetingUrl}
              onChange={(e) => setMeetingUrl(e.target.value)}
              placeholder="https://meet.google.com/..."
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="int-notes">Notizen (optional)</Label>
            <Textarea
              id="int-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Was soll der Kandidat vorbereiten?"
              rows={3}
            />
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <Button type="button" variant="outline" onClick={onClose}>
              Abbrechen
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Wird gesendet…" : "Einladung senden"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
