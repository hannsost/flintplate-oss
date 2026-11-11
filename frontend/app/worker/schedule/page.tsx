"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  ChevronLeft,
  ChevronRight,
  MapPin,
  Briefcase,
  Clock,
  Calendar,
  Building2,
  CheckCircle2,
  AlertCircle,
  XCircle,
  PlayCircle,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { scheduleApi, WorkAssignmentRead } from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function fmtDateShort(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
  });
}

function fmtTime(t: string | null): string {
  if (!t) return "";
  // t is "HH:MM:SS" from backend
  return t.slice(0, 5);
}

function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  return new Date(Number(y), Number(m) - 1).toLocaleDateString("de-DE", {
    month: "long",
    year: "numeric",
  });
}

function prevMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 2);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function nextMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

// ── Status Meta ───────────────────────────────────────────────────────────────

const STATUS_META: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  planned: {
    label: "Geplant",
    color: "text-gray-600",
    bg: "bg-gray-100",
    icon: <Calendar className="w-3.5 h-3.5" />,
  },
  confirmed: {
    label: "Bestätigt",
    color: "text-blue-700",
    bg: "bg-blue-100",
    icon: <CheckCircle2 className="w-3.5 h-3.5" />,
  },
  active: {
    label: "Aktiv",
    color: "text-green-700",
    bg: "bg-green-100",
    icon: <PlayCircle className="w-3.5 h-3.5" />,
  },
  completed: {
    label: "Abgeschlossen",
    color: "text-blue-700",
    bg: "bg-blue-100",
    icon: <CheckCircle2 className="w-3.5 h-3.5" />,
  },
  cancelled: {
    label: "Storniert",
    color: "text-red-600",
    bg: "bg-red-100",
    icon: <XCircle className="w-3.5 h-3.5" />,
  },
};

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.planned;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${meta.bg} ${meta.color}`}>
      {meta.icon}
      {meta.label}
    </span>
  );
}

// ── Assignment Card ───────────────────────────────────────────────────────────

function AssignmentCard({ a }: { a: WorkAssignmentRead }) {
  const isSingleDay = a.start_date === a.end_date;
  const dateRange = isSingleDay
    ? fmtDate(a.start_date ?? "")
    : `${fmtDateShort(a.start_date ?? "")} – ${fmtDate(a.end_date ?? "")}`;

  const shiftInfo =
    a.shift_start && a.shift_end
      ? `${fmtTime(a.shift_start)} – ${fmtTime(a.shift_end)} Uhr`
      : null;

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-sm transition-shadow">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {/* Date range */}
          <p className="text-sm font-semibold text-gray-900">{dateRange}</p>

          {/* Role / description */}
          {a.role_description && (
            <p className="text-sm text-blue-700 font-medium mt-0.5">{a.role_description}</p>
          )}

          {/* Meta row */}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {a.customer_company && (
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <Building2 className="w-3.5 h-3.5 flex-shrink-0" />
                {a.customer_company}
              </span>
            )}
            {a.location && (
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <MapPin className="w-3.5 h-3.5 flex-shrink-0" />
                {a.location}
              </span>
            )}
            {shiftInfo && (
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <Clock className="w-3.5 h-3.5 flex-shrink-0" />
                {shiftInfo}
              </span>
            )}
          </div>

          {/* Notes */}
          {a.notes && (
            <p className="mt-2 text-xs text-gray-400 italic line-clamp-2">{a.notes}</p>
          )}
        </div>

        <StatusBadge status={a.status} />
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function WorkerSchedulePage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [month, setMonth] = useState(currentMonth());
  const [assignments, setAssignments] = useState<WorkAssignmentRead[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string, m: string) => {
    setLoading(true);
    try {
      const data = await scheduleApi.list(t, m);
      setAssignments(data);
    } catch {
      setAssignments([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (token) load(token, month);
  }, [token, month, load]);

  // Group by week for better readability
  const grouped = assignments.reduce<Record<string, WorkAssignmentRead[]>>((acc, a) => {
    const d = new Date(a.start_date ?? "");
    // Week start (Monday)
    const day = d.getDay() || 7;
    const monday = new Date(d);
    monday.setDate(d.getDate() - day + 1);
    const key = monday.toISOString().slice(0, 10);
    if (!acc[key]) acc[key] = [];
    acc[key].push(a);
    return acc;
  }, {});

  const weekKeys = Object.keys(grouped).sort();

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Mein Einsatzplan</h1>
        <p className="text-sm text-gray-500 mt-0.5">Deine geplanten Einsätze und Schichten</p>
      </div>

      {/* Month navigator */}
      <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex items-center gap-2 mb-5">
        <button
          onClick={() => setMonth(prevMonth(month))}
          className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="flex-1 text-center text-sm font-semibold text-gray-800">
          {monthLabel(month)}
        </span>
        <button
          onClick={() => setMonth(nextMonth(month))}
          className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
          Lade Einsatzplan...
        </div>
      ) : assignments.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-48 text-gray-400 gap-3">
          <Briefcase className="w-10 h-10 text-gray-200" />
          <p className="text-sm">Keine Einsätze in diesem Monat</p>
        </div>
      ) : (
        <div className="space-y-6">
          {weekKeys.map((weekStart) => {
            const weekEnd = new Date(weekStart);
            weekEnd.setDate(weekEnd.getDate() + 6);
            const label = `KW – ${fmtDateShort(weekStart)} bis ${fmtDateShort(weekEnd.toISOString().slice(0, 10))}`;
            return (
              <div key={weekStart}>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  {label}
                </p>
                <div className="space-y-3">
                  {grouped[weekStart].map((a) => (
                    <AssignmentCard key={a.id} a={a} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
