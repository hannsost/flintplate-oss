"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Clock,
  Play,
  Square,
  Send,
  Download,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Edit2,
  ChevronLeft,
  ChevronRight,
  Loader2,
  MapPin,
  FileEdit,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { timeApi, ApiError } from "@/lib/api";
import type { TimeEntryRead, TimeEntrySummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// ── constants ─────────────────────────────────────────────────────────────────

const COST_CENTERS = [
  { value: "CC-LAGER",    label: "Lager & Logistik" },
  { value: "CC-PRODUKT",  label: "Produktion" },
  { value: "CC-VERSAND",  label: "Versand & Verpackung" },
  { value: "CC-REINIG",   label: "Reinigung & Hausmeister" },
  { value: "CC-BUERO",    label: "Büro & Verwaltung" },
  { value: "CC-MONTAGE",  label: "Montage & Technik" },
  { value: "CC-AUSHILFE", label: "Aushilfe / Sonstiges" },
];

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtMinutes(min: number | null | undefined): string {
  if (min === null || min === undefined) return "–";
  if (min === 0) return "0";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h ${m > 0 ? m + "m" : ""}`.trim();
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });
}

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function prevMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return mo === 1 ? `${y - 1}-12` : `${y}-${String(mo - 1).padStart(2, "0")}`;
}

function nextMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return mo === 12 ? `${y + 1}-01` : `${y}-${String(mo + 1).padStart(2, "0")}`;
}

function monthLabel(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1, 1).toLocaleDateString("de-DE", { month: "long", year: "numeric" });
}

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  draft:                { label: "Entwurf",           color: "bg-gray-100 text-gray-600",    icon: Edit2 },
  submitted:            { label: "Eingereicht",        color: "bg-blue-100 text-blue-700",    icon: Send },
  approved:             { label: "Freigegeben",        color: "bg-blue-100 text-blue-700", icon: CheckCircle2 },
  rejected:             { label: "Abgelehnt",          color: "bg-red-100 text-red-700",      icon: XCircle },
  correction_requested: { label: "Korrektur beantragt", color: "bg-amber-100 text-amber-700", icon: FileEdit },
};

// ── Main component ────────────────────────────────────────────────────────────

export default function WorkerTimePage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [entries, setEntries] = useState<TimeEntryRead[]>([]);
  const [summary, setSummary] = useState<TimeEntrySummary | null>(null);
  const [month, setMonth] = useState(currentMonth());
  const [loading, setLoading] = useState(true);
  const [openEntry, setOpenEntry] = useState<TimeEntryRead | null>(null); // active clock-in

  // Forms
  const [clockInDrawer, setClockInDrawer] = useState(false);
  const [clockOutDrawer, setClockOutDrawer] = useState(false);
  const [correctionDrawer, setCorrectionDrawer] = useState<TimeEntryRead | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Clock-in form
  const [locationNote, setLocationNote] = useState("");
  const [projectCode, setProjectCode] = useState("");
  // Clock-out form
  const [breakMinutes, setBreakMinutes] = useState("0");
  // Correction form
  const [corrNewIn, setCorrNewIn] = useState("");
  const [corrNewOut, setCorrNewOut] = useState("");
  const [corrNewBreak, setCorrNewBreak] = useState("");
  const [corrReason, setCorrReason] = useState("");

  const load = useCallback(async (t: string, m: string) => {
    setLoading(true);
    try {
      const [list, sum] = await Promise.all([
        timeApi.list(t, m),
        timeApi.summary(t, m),
      ]);
      setEntries(list);
      setSummary(sum);
      setOpenEntry(list.find((e) => e.status === "draft" && !e.clock_out) ?? null);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
    load(t, month);
  }, [router, load, month]);

  // ── clock in ────────────────────────────────────────────────────────────────

  async function handleClockIn() {
    setActionLoading(true); setActionError(null);
    try {
      await timeApi.clockIn(token, { location_note: locationNote || undefined, project_code: projectCode || undefined });
      setClockInDrawer(false);
      setLocationNote(""); setProjectCode("");
      await load(token, month);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.detail : "Fehler beim Einstempeln.");
    } finally { setActionLoading(false); }
  }

  // ── clock out ────────────────────────────────────────────────────────────────

  async function handleClockOut() {
    if (!openEntry) return;
    setActionLoading(true); setActionError(null);
    try {
      await timeApi.clockOut(token, openEntry.id, {
        clock_out: new Date().toISOString(),
        break_minutes: parseInt(breakMinutes) || 0,
      });
      setClockOutDrawer(false);
      setBreakMinutes("0");
      await load(token, month);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.detail : "Fehler beim Ausstempeln.");
    } finally { setActionLoading(false); }
  }

  // ── submit ───────────────────────────────────────────────────────────────────

  async function handleSubmit(entryId: string) {
    setActionLoading(true);
    try {
      await timeApi.submit(token, entryId);
      await load(token, month);
    } catch { /* ignore */ }
    finally { setActionLoading(false); }
  }

  // ── correction ────────────────────────────────────────────────────────────────

  async function handleCorrection() {
    if (!correctionDrawer) return;
    setActionLoading(true); setActionError(null);
    try {
      await timeApi.requestCorrection(token, correctionDrawer.id, {
        new_clock_in: corrNewIn ? new Date(corrNewIn).toISOString() : undefined,
        new_clock_out: corrNewOut ? new Date(corrNewOut).toISOString() : undefined,
        new_break_minutes: corrNewBreak ? parseInt(corrNewBreak) : undefined,
        reason: corrReason,
      });
      setCorrectionDrawer(null);
      setCorrNewIn(""); setCorrNewOut(""); setCorrNewBreak(""); setCorrReason("");
      await load(token, month);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.detail : "Fehler.");
    } finally { setActionLoading(false); }
  }

  // ── export ────────────────────────────────────────────────────────────────────

  async function handleExport() {
    try {
      const data = await timeApi.export(token, month);
      const rows = [
        ["Datum", "Einstempeln", "Ausstempeln", "Pause (min)", "Netto (h)", "Ort", "Projekt"].join(";"),
        ...data.rows.map((r: Record<string, string | number | null>) =>
          [r.date, r.clock_in, r.clock_out ?? "", r.break_minutes, r.net_hours, r.location ?? "", r.project ?? ""].join(";")
        ),
      ].join("\n");
      const blob = new Blob([rows], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `stunden_${month}.csv`;
      a.click(); URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  }

  // ── render ────────────────────────────────────────────────────────────────────

  const now = new Date();
  const isCurrentMonth = month === currentMonth();

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Clock size={22} className="text-blue-600" />
            Zeiterfassung
          </h1>
          {openEntry && (
            <p className="mt-0.5 text-sm text-blue-600 font-medium flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
              Eingestempelt seit {fmtTime(openEntry.clock_in)}
            </p>
          )}
        </div>

        {/* Clock-in / Clock-out CTA */}
        {!openEntry ? (
          <Button onClick={() => { setClockInDrawer(true); setActionError(null); }} className="flex items-center gap-2">
            <Play size={15} />
            Einstempeln
          </Button>
        ) : (
          <Button
            onClick={() => { setClockOutDrawer(true); setActionError(null); }}
            className="flex items-center gap-2 bg-red-600 hover:bg-red-700"
          >
            <Square size={14} fill="currentColor" />
            Ausstempeln
          </Button>
        )}
      </div>

      {/* Month nav + summary */}
      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between mb-4">
          <button
            type="button"
            aria-label="Vorheriger Monat"
            onClick={() => setMonth((current) => prevMonth(current))}
            className="rounded p-1 hover:bg-gray-100 text-gray-500"
          >
            <ChevronLeft size={18} />
          </button>
          <h2 className="text-sm font-semibold text-gray-700">{monthLabel(month)}</h2>
          <button
            type="button"
            aria-label="Nächster Monat"
            onClick={() => setMonth((current) => nextMonth(current))}
            disabled={isCurrentMonth}
            className="rounded p-1 hover:bg-gray-100 text-gray-500 disabled:opacity-30"
          >
            <ChevronRight size={18} />
          </button>
        </div>

        {summary && (
          <div className="grid grid-cols-3 gap-3 text-center text-sm">
            <div className="rounded-lg bg-blue-50 px-3 py-2">
              <p className="text-xs text-blue-600 font-medium">Freigegeben</p>
              <p className="text-lg font-bold text-blue-700">{fmtMinutes(summary.approved_minutes)}</p>
            </div>
            <div className="rounded-lg bg-blue-50 px-3 py-2">
              <p className="text-xs text-blue-600 font-medium">Eingereicht</p>
              <p className="text-lg font-bold text-blue-700">{fmtMinutes(summary.submitted_minutes)}</p>
            </div>
            <div className="rounded-lg bg-gray-50 px-3 py-2">
              <p className="text-xs text-gray-500 font-medium">Entwürfe</p>
              <p className="text-lg font-bold text-gray-700">{fmtMinutes(summary.draft_minutes)}</p>
            </div>
          </div>
        )}
      </div>

      {/* Export button */}
      <div className="flex justify-end">
        <button
          onClick={handleExport}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          <Download size={14} />
          CSV exportieren
        </button>
      </div>

      {/* Entries list */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 size={24} className="animate-spin text-blue-500" />
        </div>
      ) : entries.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-200 py-12 text-center text-sm text-gray-400">
          Keine Einträge für diesen Monat
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map((entry) => {
            const cfg = STATUS_CONFIG[entry.status] ?? STATUS_CONFIG.draft;
            const StatusIcon = cfg.icon;
            return (
              <div
                key={entry.id}
                className="rounded-xl border border-gray-200 bg-white px-4 py-3 flex items-center justify-between gap-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-gray-900">{fmtDate(entry.entry_date)}</span>
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.color}`}>
                      <StatusIcon size={11} />
                      {cfg.label}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-3 text-xs text-gray-500">
                    <span>{fmtTime(entry.clock_in)} – {fmtTime(entry.clock_out)}</span>
                    {entry.net_minutes && <span className="font-medium">{fmtMinutes(entry.net_minutes)}</span>}
                    {entry.location_note && (
                      <span className="flex items-center gap-0.5">
                        <MapPin size={10} /> {entry.location_note}
                      </span>
                    )}
                  </div>
                  {entry.rejection_note && (
                    <p className="mt-1 text-xs text-red-500">{entry.rejection_note}</p>
                  )}
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {/* Submit button for complete drafts */}
                  {entry.status === "draft" && entry.clock_out && (
                    <button
                      onClick={() => handleSubmit(entry.id)}
                      disabled={actionLoading}
                      className="flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      <Send size={11} />
                      Einreichen
                    </button>
                  )}
                  {/* Correction for submitted/approved/rejected */}
                  {["submitted", "approved", "rejected"].includes(entry.status) && (
                    <button
                      onClick={() => { setCorrectionDrawer(entry); setActionError(null); }}
                      className="rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:border-gray-300 hover:text-gray-900"
                    >
                      Korrektur
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Clock-in drawer ── */}
      {clockInDrawer && (
        <SimpleDrawer title="Einstempeln" onClose={() => setClockInDrawer(false)}>
          <div className="space-y-4">
            <div className="rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-700 font-medium text-center">
              {now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })} Uhr
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Einsatzort (optional)</Label>
              <Input value={locationNote} onChange={(e) => setLocationNote(e.target.value)} placeholder="z.B. Kunde XY, Lager Berlin" className="text-sm" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Kostenstelle (optional)</Label>
              <select
                value={projectCode}
                onChange={(e) => setProjectCode(e.target.value)}
                className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">– Keine Kostenstelle –</option>
                {COST_CENTERS.map((cc) => (
                  <option key={cc.value} value={cc.value}>{cc.label}</option>
                ))}
              </select>
            </div>
            {actionError && <p className="text-xs text-red-500 flex items-center gap-1"><AlertCircle size={12} />{actionError}</p>}
            <Button onClick={handleClockIn} disabled={actionLoading} className="w-full flex items-center gap-2">
              {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Jetzt einstempeln
            </Button>
          </div>
        </SimpleDrawer>
      )}

      {/* ── Clock-out drawer ── */}
      {clockOutDrawer && openEntry && (
        <SimpleDrawer title="Ausstempeln" onClose={() => setClockOutDrawer(false)}>
          <div className="space-y-4">
            <div className="rounded-lg bg-gray-50 px-4 py-3 text-sm text-gray-600 space-y-1">
              <p>Eingestempelt: <strong>{fmtTime(openEntry.clock_in)}</strong></p>
              {openEntry.location_note && <p className="text-xs text-gray-400"><MapPin size={10} className="inline mr-0.5" />{openEntry.location_note}</p>}
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Pause (Minuten)</Label>
              <Input
                type="number"
                min={0}
                max={480}
                value={breakMinutes}
                onChange={(e) => setBreakMinutes(e.target.value)}
                className="text-sm"
              />
            </div>
            {actionError && <p className="text-xs text-red-500 flex items-center gap-1"><AlertCircle size={12} />{actionError}</p>}
            <Button
              onClick={handleClockOut}
              disabled={actionLoading}
              className="w-full flex items-center gap-2 bg-red-600 hover:bg-red-700"
            >
              {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <Square size={14} fill="currentColor" />}
              Jetzt ausstempeln
            </Button>
          </div>
        </SimpleDrawer>
      )}

      {/* ── Correction drawer ── */}
      {correctionDrawer && (
        <SimpleDrawer title="Korrektur beantragen" onClose={() => setCorrectionDrawer(null)}>
          <div className="space-y-4">
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
              Aktuell: {fmtTime(correctionDrawer.clock_in)} – {fmtTime(correctionDrawer.clock_out)} · {correctionDrawer.break_minutes} min Pause
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Neues Einstempeln</Label>
                <Input type="datetime-local" value={corrNewIn} onChange={(e) => setCorrNewIn(e.target.value)} className="text-xs" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Neues Ausstempeln</Label>
                <Input type="datetime-local" value={corrNewOut} onChange={(e) => setCorrNewOut(e.target.value)} className="text-xs" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Neue Pause (min)</Label>
              <Input type="number" min={0} value={corrNewBreak} onChange={(e) => setCorrNewBreak(e.target.value)} className="text-sm" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Begründung *</Label>
              <textarea
                rows={3}
                value={corrReason}
                onChange={(e) => setCorrReason(e.target.value)}
                placeholder="Warum wird die Korrektur benötigt?"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            </div>
            {actionError && <p className="text-xs text-red-500 flex items-center gap-1"><AlertCircle size={12} />{actionError}</p>}
            <Button onClick={handleCorrection} disabled={actionLoading || !corrReason} className="w-full flex items-center gap-2">
              {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <FileEdit size={14} />}
              Korrektur einreichen
            </Button>
          </div>
        </SimpleDrawer>
      )}
    </main>
  );
}

function SimpleDrawer({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} />
      <aside className="fixed bottom-0 left-0 right-0 z-50 rounded-t-2xl bg-white shadow-2xl sm:bottom-auto sm:left-auto sm:right-4 sm:top-16 sm:w-96 sm:rounded-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700"><XCircle size={18} /></button>
        </div>
        <div className="px-5 py-5">{children}</div>
      </aside>
    </>
  );
}
