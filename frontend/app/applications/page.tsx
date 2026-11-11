"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import {
  applicationsApi,
  interviewScheduleApi,
  ApiError,
  type ApplicationRead,
  type ApplicationStatus,
  type KanbanBoard,
  type ApplicationCreate,
  type InterviewScheduleRead,
} from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { wsClient } from "@/lib/websocket";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

// ── Status config ─────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  ApplicationStatus,
  { label: string; color: string; bg: string; border: string }
> = {
  research:  { label: "Recherche",       color: "text-gray-700",   bg: "bg-gray-50",    border: "border-gray-200" },
  applied:   { label: "Beworben",        color: "text-blue-700",   bg: "bg-blue-50",    border: "border-blue-200" },
  screening: { label: "Screening",       color: "text-purple-700", bg: "bg-purple-50",  border: "border-purple-200" },
  interview: { label: "Interview",       color: "text-yellow-700", bg: "bg-yellow-50",  border: "border-yellow-200" },
  offer:     { label: "Angebot",         color: "text-green-700",  bg: "bg-green-50",   border: "border-green-200" },
  rejected:  { label: "Abgelehnt",       color: "text-red-700",    bg: "bg-red-50",     border: "border-red-200" },
  withdrawn: { label: "Zurückgezogen",   color: "text-slate-500",  bg: "bg-slate-50",   border: "border-slate-200" },
};

const STATUS_ORDER: ApplicationStatus[] = [
  "research", "applied", "screening", "interview", "offer", "rejected", "withdrawn",
];

// ── Application card ──────────────────────────────────────────────────────

function AppCard({
  app,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  app: ApplicationRead;
  onDragStart: (e: React.DragEvent, app: ApplicationRead) => void;
  onDragEnd: () => void;
  onClick: (app: ApplicationRead) => void;
}) {
  const cfg = STATUS_CONFIG[app.status];
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, app)}
      onDragEnd={onDragEnd}
      onClick={() => onClick(app)}
      className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm cursor-grab active:cursor-grabbing hover:shadow-md transition-shadow select-none"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium text-gray-900 text-sm leading-snug truncate">{app.position}</p>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{app.company}</p>
        </div>
        <span className={`shrink-0 text-xs font-medium px-1.5 py-0.5 rounded ${cfg.bg} ${cfg.color} border ${cfg.border}`}>
          {app.history.length}
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-2 flex-wrap">
        {app.applied_at && (
          <p className="text-xs text-gray-400">
            Beworben {new Date(app.applied_at).toLocaleDateString("de-DE")}
          </p>
        )}
        {app.source_platform && (
          <span className="rounded-full bg-gray-100 border border-gray-200 px-1.5 py-0.5 text-[10px] text-gray-500">
            {app.source_platform}
          </span>
        )}
        {app.status === "interview" && (
          <span className="ml-auto shrink-0 text-xs text-yellow-600" title="Interview geplant">📅</span>
        )}
      </div>
      {app.job_url && (
        <a
          href={app.job_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="mt-1 block text-xs text-blue-600 hover:underline truncate"
        >
          Stellenanzeige →
        </a>
      )}
    </div>
  );
}

// ── Kanban column ─────────────────────────────────────────────────────────

function KanbanColumnView({
  status,
  label,
  apps,
  onDragStart,
  onDragEnd,
  onDrop,
  onCardClick,
}: {
  status: ApplicationStatus;
  label: string;
  apps: ApplicationRead[];
  onDragStart: (e: React.DragEvent, app: ApplicationRead) => void;
  onDragEnd: () => void;
  onDrop: (status: ApplicationStatus) => void;
  onCardClick: (app: ApplicationRead) => void;
}) {
  const [over, setOver] = useState(false);
  const cfg = STATUS_CONFIG[status];

  return (
    <div
      className={`flex flex-col rounded-xl border transition-colors min-w-[220px] w-[220px] shrink-0 ${
        over ? "border-blue-400 bg-blue-50/40" : `border-gray-200 ${cfg.bg}`
      }`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={() => { setOver(false); onDrop(status); }}
    >
      <div className={`px-3 py-2 border-b ${cfg.border} flex items-center justify-between`}>
        <span className={`text-xs font-semibold uppercase tracking-wide ${cfg.color}`}>
          {label}
        </span>
        <Badge variant="secondary" className="text-xs h-5 px-1.5">
          {apps.length}
        </Badge>
      </div>
      <div className="flex flex-col gap-2 p-2 flex-1 overflow-y-auto max-h-[calc(100vh-220px)]">
        {apps.map((app) => (
          <AppCard
            key={app.id}
            app={app}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onClick={onCardClick}
          />
        ))}
        {apps.length === 0 && (
          <div className="flex-1 flex items-center justify-center py-6">
            <p className="text-xs text-gray-400">Keine Bewerbungen</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Create modal ──────────────────────────────────────────────────────────

function CreateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (app: ApplicationRead) => void;
}) {
  const [form, setForm] = useState<ApplicationCreate>({
    company: "",
    position: "",
    status: "research",
    job_url: "",
    notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const token = auth.getAccess();
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      const payload: ApplicationCreate = {
        company: form.company,
        position: form.position,
        status: form.status,
        ...(form.job_url ? { job_url: form.job_url } : {}),
        ...(form.notes ? { notes: form.notes } : {}),
      };
      const created = await applicationsApi.create(token, payload);
      onCreated(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Fehler beim Speichern.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Neue Bewerbung</h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <Label htmlFor="company">Unternehmen *</Label>
            <Input
              id="company"
              required
              value={form.company}
              onChange={(e) => setForm({ ...form, company: e.target.value })}
              placeholder="Acme GmbH"
            />
          </div>
          <div>
            <Label htmlFor="position">Stelle *</Label>
            <Input
              id="position"
              required
              value={form.position}
              onChange={(e) => setForm({ ...form, position: e.target.value })}
              placeholder="Backend Engineer"
            />
          </div>
          <div>
            <Label htmlFor="status">Status</Label>
            <select
              id="status"
              value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value as ApplicationStatus })}
              className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {STATUS_ORDER.map((s) => (
                <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="job_url">Stellen-URL</Label>
            <Input
              id="job_url"
              type="url"
              value={form.job_url ?? ""}
              onChange={(e) => setForm({ ...form, job_url: e.target.value })}
              placeholder="https://..."
            />
          </div>
          <div>
            <Label htmlFor="notes">Notizen</Label>
            <Textarea
              id="notes"
              value={form.notes ?? ""}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              rows={3}
              placeholder="Anmerkungen zur Stelle…"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-2 justify-end pt-1">
            <Button type="button" variant="outline" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Wird gespeichert…" : "Anlegen"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Interview section (inside detail drawer) ──────────────────────────────

function InterviewSection({ app }: { app: ApplicationRead }) {
  const [interview, setInterview] = useState<InterviewScheduleRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { setLoading(false); return; }
    interviewScheduleApi.get(token, app.id)
      .then(setInterview)
      .catch(() => setInterview(null))
      .finally(() => setLoading(false));
  }, [app.id]);

  async function handleAction(newStatus: "confirmed" | "declined") {
    const token = auth.getAccess();
    if (!token) return;
    setActing(true);
    try {
      const updated = await interviewScheduleApi.updateStatus(token, app.id, newStatus);
      setInterview(updated);
    } finally {
      setActing(false);
    }
  }

  if (loading) return <div className="h-16 animate-pulse rounded-lg bg-gray-100" />;
  if (!interview) return null;

  const dt = new Date(interview.scheduled_at);
  const dateStr = dt.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const timeStr = dt.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });

  const sColors: Record<string, string> = {
    proposed:  "border-yellow-200 bg-yellow-50",
    confirmed: "border-green-200 bg-green-50",
    declined:  "border-red-200 bg-red-50",
    cancelled: "border-gray-200 bg-gray-50",
  };
  const sLabels: Record<string, string> = {
    proposed:  "Ausstehend",
    confirmed: "Bestätigt",
    declined:  "Abgelehnt",
    cancelled: "Abgesagt",
  };

  return (
    <div className={`rounded-lg border p-4 space-y-3 ${sColors[interview.status] ?? "border-gray-200 bg-gray-50"}`}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-700">Interview-Termin</p>
        <span className="text-xs font-medium text-gray-500">{sLabels[interview.status] ?? interview.status}</span>
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-gray-900">📅 {dateStr}</p>
        <p className="text-sm text-gray-600">🕐 {timeStr} Uhr</p>
        {interview.meeting_url && (
          <a
            href={interview.meeting_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block text-sm text-blue-600 hover:underline truncate"
          >
            🔗 Meeting öffnen
          </a>
        )}
        {interview.notes && (
          <p className="text-xs text-gray-500 mt-1 whitespace-pre-line">{interview.notes}</p>
        )}
      </div>
      {interview.status === "proposed" && (
        <div className="flex gap-2 pt-1">
          <Button
            size="sm"
            className="flex-1 bg-green-600 hover:bg-green-700 text-white"
            disabled={acting}
            onClick={() => handleAction("confirmed")}
          >
            ✓ Bestätigen
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="flex-1 border-red-300 text-red-600 hover:bg-red-50"
            disabled={acting}
            onClick={() => handleAction("declined")}
          >
            ✗ Ablehnen
          </Button>
        </div>
      )}
      {interview.status === "confirmed" && (
        <div className="flex gap-2 pt-1 flex-wrap">
          <a
            href={(() => {
              const start = new Date(interview.scheduled_at);
              const end = new Date(start.getTime() + 60 * 60 * 1000);
              const fmt = (d: Date) => d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
              const desc = interview.meeting_url ? `Meeting: ${interview.meeting_url}` : "";
              return `https://calendar.google.com/calendar/render?action=TEMPLATE&text=Interview&dates=${fmt(start)}/${fmt(end)}&details=${encodeURIComponent(desc)}`;
            })()}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:border-gray-300 transition-colors"
          >
            📅 Google Kalender
          </a>
          <button
            onClick={() => {
              const start = new Date(interview.scheduled_at);
              const end = new Date(start.getTime() + 60 * 60 * 1000);
              const fmt = (d: Date) => d.toISOString().replace(/[-:.]/g, "").slice(0, 15) + "Z";
              const ics = [
                "BEGIN:VCALENDAR", "VERSION:2.0",
                "BEGIN:VEVENT",
                `DTSTART:${fmt(start)}`,
                `DTEND:${fmt(end)}`,
                "SUMMARY:Interview",
                ...(interview.meeting_url ? [`URL:${interview.meeting_url}`] : []),
                "END:VEVENT", "END:VCALENDAR",
              ].join("\r\n");
              const blob = new Blob([ics], { type: "text/calendar" });
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = "interview.ics";
              a.click();
            }}
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:border-gray-300 transition-colors"
          >
            ↓ .ics
          </button>
        </div>
      )}
    </div>
  );
}

// ── Detail / edit drawer ──────────────────────────────────────────────────

function DetailDrawer({
  app,
  onClose,
  onUpdated,
  onDeleted,
}: {
  app: ApplicationRead;
  onClose: () => void;
  onUpdated: (app: ApplicationRead) => void;
  onDeleted: (id: string) => void;
}) {
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<ApplicationStatus>(app.status);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const cfg = STATUS_CONFIG[app.status];

  async function handleStatusChange(newStatus: ApplicationStatus) {
    const token = auth.getAccess();
    if (!token) return;
    setSaving(true);
    try {
      const updated = await applicationsApi.update(token, app.id, {
        status: newStatus,
        ...(note ? { note } : {}),
      });
      setNote("");
      setStatus(newStatus);
      onUpdated(updated);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Bewerbung bei "${app.company}" wirklich löschen?`)) return;
    const token = auth.getAccess();
    if (!token) return;
    setDeleting(true);
    try {
      await applicationsApi.delete(token, app.id);
      onDeleted(app.id);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="ml-auto h-full w-full max-w-md bg-white shadow-2xl overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className={`px-5 py-4 border-b ${cfg.border} ${cfg.bg}`}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold text-gray-900">{app.position}</h2>
              <p className="text-sm text-gray-500 mt-0.5">{app.company}</p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none mt-0.5">✕</button>
          </div>
          <span className={`mt-2 inline-block text-xs font-medium px-2 py-0.5 rounded ${cfg.bg} ${cfg.color} border ${cfg.border}`}>
            {STATUS_CONFIG[app.status].label}
          </span>
        </div>

        <div className="p-5 space-y-5">
          {/* Links */}
          {app.job_url && (
            <a href={app.job_url} target="_blank" rel="noopener noreferrer"
              className="block text-sm text-blue-600 hover:underline truncate">
              {app.job_url}
            </a>
          )}

          {/* Notes */}
          {app.notes && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Notizen</p>
              <p className="text-sm text-gray-700 whitespace-pre-line">{app.notes}</p>
            </div>
          )}

          {/* Status change */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-gray-500">Status ändern</p>
            <div className="flex gap-2">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Notiz zur Änderung (optional)"
                className="flex-1 rounded-md border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {STATUS_ORDER.map((s) => (
                <button
                  key={s}
                  disabled={s === app.status || saving}
                  onClick={() => handleStatusChange(s)}
                  className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                    s === app.status
                      ? `${STATUS_CONFIG[s].bg} ${STATUS_CONFIG[s].color} ${STATUS_CONFIG[s].border} font-semibold cursor-default`
                      : "border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50"
                  }`}
                >
                  {STATUS_CONFIG[s].label}
                </button>
              ))}
            </div>
          </div>

          {/* History */}
          <div>
            <p className="text-xs font-medium text-gray-500 mb-2">Verlauf</p>
            <div className="space-y-2">
              {[...app.history].reverse().map((h) => (
                <div key={h.id} className="flex items-start gap-2 text-xs">
                  <span className="text-gray-400 shrink-0 mt-0.5">
                    {new Date(h.changed_at).toLocaleDateString("de-DE", {
                      day: "2-digit", month: "2-digit", year: "2-digit",
                    })}
                  </span>
                  <span className="text-gray-700">
                    {h.from_status
                      ? `${STATUS_CONFIG[h.from_status].label} → ${STATUS_CONFIG[h.to_status].label}`
                      : `Angelegt als ${STATUS_CONFIG[h.to_status].label}`}
                    {h.note && <span className="text-gray-400 ml-1">– {h.note}</span>}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Interview schedule */}
          <InterviewSection app={app} />

          {/* Danger zone */}
          <div className="pt-2 border-t border-gray-100">
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="text-xs text-red-500 hover:text-red-700 transition-colors"
            >
              {deleting ? "Wird gelöscht…" : "Bewerbung löschen"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function ApplicationsPage() {
  const router = useRouter();
  const [board, setBoard] = useState<KanbanBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<ApplicationRead | null>(null);
  const dragApp = useRef<ApplicationRead | null>(null);

  const fetchBoard = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    setLoading(true);
    setError(null);
    try {
      const data = await applicationsApi.getKanban(token);
      setBoard(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Fehler beim Laden.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run once on mount only

  useEffect(() => {
    fetchBoard();

    // Subscribe to real-time updates from server
    const token = auth.getAccess();
    if (token) {
      wsClient.connect(token);
      const offCreated = wsClient.on("application.created", () => fetchBoard());
      const offUpdated = wsClient.on("application.updated", () => fetchBoard());
      const offDeleted = wsClient.on("application.deleted", (e) => {
        const id = e.payload.id as string;
        handleDeleted(id);
      });
      return () => { offCreated(); offUpdated(); offDeleted(); };
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchBoard]);

  function handleDragStart(e: React.DragEvent, app: ApplicationRead) {
    dragApp.current = app;
    e.dataTransfer.effectAllowed = "move";
  }

  async function handleDrop(targetStatus: ApplicationStatus) {
    const app = dragApp.current;
    dragApp.current = null;
    if (!app || app.status === targetStatus) return;

    const token = auth.getAccess();
    if (!token) return;

    // Optimistic update
    setBoard((prev) => {
      if (!prev) return prev;
      const columns = prev.columns.map((col) => {
        if (col.status === app.status) {
          return { ...col, applications: col.applications.filter((a) => a.id !== app.id) };
        }
        if (col.status === targetStatus) {
          return { ...col, applications: [...col.applications, { ...app, status: targetStatus }] };
        }
        return col;
      });
      return { ...prev, columns };
    });

    try {
      await applicationsApi.update(token, app.id, { status: targetStatus });
      // Refresh for accurate data (applied_at, history)
      fetchBoard();
    } catch {
      fetchBoard(); // revert on error
    }
  }

  function handleUpdated(updated: ApplicationRead) {
    setBoard((prev) => {
      if (!prev) return prev;
      const columns = prev.columns.map((col) => ({
        ...col,
        applications: col.applications.map((a) =>
          a.id === updated.id ? updated : a
        ),
      }));
      // Move card if status changed
      const movedColumns = columns.map((col) => {
        if (col.status === updated.status) {
          const exists = col.applications.some((a) => a.id === updated.id);
          if (!exists) return { ...col, applications: [...col.applications, updated] };
        } else {
          return { ...col, applications: col.applications.filter((a) => a.id !== updated.id) };
        }
        return col;
      });
      return { ...prev, columns: movedColumns };
    });
    setSelected(updated);
  }

  function handleDeleted(id: string) {
    setBoard((prev) => {
      if (!prev) return prev;
      const columns = prev.columns.map((col) => ({
        ...col,
        applications: col.applications.filter((a) => a.id !== id),
      }));
      return { ...prev, total: prev.total - 1, columns };
    });
    setSelected(null);
  }

  function handleCreated(app: ApplicationRead) {
    setBoard((prev) => {
      if (!prev) return prev;
      const columns = prev.columns.map((col) =>
        col.status === app.status
          ? { ...col, applications: [app, ...col.applications] }
          : col
      );
      return { ...prev, total: prev.total + 1, columns };
    });
    setShowCreate(false);
  }

  return (
    <>
      <Navbar />
      <main className="px-4 py-6">
        <div className="flex items-center justify-between mb-5 max-w-full">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Bewerbungs-Tracker</h1>
            {board && (
              <p className="text-sm text-gray-400 mt-0.5">{board.total} Bewerbungen</p>
            )}
          </div>
          <Button onClick={() => setShowCreate(true)} size="sm">
            + Neue Bewerbung
          </Button>
        </div>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-4">
            {STATUS_ORDER.map((status) => {
              const col = board?.columns.find((c) => c.status === status);
              return (
                <KanbanColumnView
                  key={status}
                  status={status}
                  label={STATUS_CONFIG[status].label}
                  apps={col?.applications ?? []}
                  onDragStart={handleDragStart}
                  onDragEnd={() => { dragApp.current = null; }}
                  onDrop={handleDrop}
                  onCardClick={setSelected}
                />
              );
            })}
          </div>
        )}
      </main>

      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}

      {selected && (
        <DetailDrawer
          app={selected}
          onClose={() => setSelected(null)}
          onUpdated={handleUpdated}
          onDeleted={handleDeleted}
        />
      )}
    </>
  );
}
