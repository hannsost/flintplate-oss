"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Users,
  Search,
  UserPlus,
  CheckSquare,
  Square,
  ToggleLeft,
  ToggleRight,
  ChevronDown,
  X,
  Save,
  Loader2,
  AlertCircle,
  UserCheck,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { workerManagementApi, teamsApi, ApiError } from "@/lib/api";
import type { WorkerListRead, WorkerSettingsUpdate, WorkerActivateRequest, TeamRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// ── constants ─────────────────────────────────────────────────────────────────

const EMPLOYMENT_LABELS: Record<string, string> = {
  fulltime: "Vollzeit",
  parttime: "Teilzeit",
  minijob: "Minijob",
  temp: "Zeitarbeit",
};

const MODULE_LABELS: Record<string, string> = {
  timetracking:       "Zeiterfassung",
  schedule:           "Einsatzplan",
  messages:           "Nachrichten",
  documents:          "Dokumente",
  absences:           "Abwesenheiten",
  equipment:          "Ausrüstung",
  tasks:              "Aufgaben",
  payroll:            "Lohn",
  tickets:            "Tickets",
  profile_selfservice:"Profil Self-Service",
};

// ── types ─────────────────────────────────────────────────────────────────────

type DrawerState =
  | { mode: "closed" }
  | { mode: "settings"; worker: WorkerListRead }
  | { mode: "activate" };

// ── main component ────────────────────────────────────────────────────────────

export default function WorkersManagementPage() {
  const router = useRouter();
  const [workers, setWorkers] = useState<WorkerListRead[]>([]);
  const [teams, setTeams] = useState<TeamRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [teamFilter, setTeamFilter] = useState("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drawer, setDrawer] = useState<DrawerState>({ mode: "closed" });
  const [bulkLoading, setBulkLoading] = useState(false);
  const [token, setToken] = useState<string>("");

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
    Promise.all([
      workerManagementApi.list(t),
      teamsApi.list(t).catch(() => [] as TeamRead[]),
    ])
      .then(([ws, ts]) => { setWorkers(ws); setTeams(ts); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [router]);

  // ── selection ──────────────────────────────────────────────────────────────

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((w) => w.id)));
    }
  }

  // ── bulk actions ──────────────────────────────────────────────────────────

  async function handleBulk(action: "activate" | "deactivate") {
    if (!selected.size || !token) return;
    setBulkLoading(true);
    try {
      await workerManagementApi.bulk(token, {
        user_ids: [...selected],
        action,
      });
      const updated = await workerManagementApi.list(token);
      setWorkers(updated);
      setSelected(new Set());
    } catch { /* ignore */ }
    finally { setBulkLoading(false); }
  }

  // ── inline toggle ─────────────────────────────────────────────────────────

  async function handleToggleActive(worker: WorkerListRead) {
    if (!token) return;
    const newActive = !worker.settings?.is_active;
    try {
      await workerManagementApi.updateSettings(token, worker.id, { is_active: newActive });
      setWorkers((prev) =>
        prev.map((w) =>
          w.id === worker.id && w.settings
            ? { ...w, settings: { ...w.settings, is_active: newActive } }
            : w
        )
      );
    } catch { /* ignore */ }
  }

  // ── filtering ─────────────────────────────────────────────────────────────

  const filtered = workers.filter((w) => {
    const q = search.toLowerCase();
    const matchSearch = !q || w.full_name?.toLowerCase().includes(q) || w.email.toLowerCase().includes(q);
    const matchTeam = teamFilter === "all"
      ? true
      : teamFilter === "none"
        ? !w.team
        : w.team?.id === teamFilter;
    return matchSearch && matchTeam;
  });

  const allSelected = filtered.length > 0 && selected.size === filtered.length;

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <div className="relative min-h-screen">
      <main className="mx-auto max-w-6xl px-4 py-8">

        {/* Page header */}
        <div className="mb-6 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <Users size={22} className="text-blue-600" />
              Worker-Verwaltung
            </h1>
            <p className="mt-0.5 text-sm text-gray-500">
              {workers.length} Worker · {workers.filter((w) => w.settings?.is_active).length} aktiv
            </p>
          </div>
          <Button
            onClick={() => setDrawer({ mode: "activate" })}
            className="flex items-center gap-2"
          >
            <UserPlus size={15} />
            Kandidat aktivieren
          </Button>
        </div>

        {/* Search + bulk bar */}
        <div className="mb-4 flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <Input
              placeholder="Name oder E-Mail suchen…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 text-sm"
            />
          </div>

          {/* Team filter */}
          {teams.length > 0 && (
            <select
              value={teamFilter}
              onChange={(e) => setTeamFilter(e.target.value)}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Alle Teams</option>
              <option value="none">Kein Team</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          )}

          {/* Bulk action bar — slides in when something is selected */}
          {selected.size > 0 && (
            <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm">
              <span className="font-medium text-blue-700">{selected.size} ausgewählt</span>
              <div className="mx-1 h-4 w-px bg-blue-200" />
              <button
                onClick={() => handleBulk("activate")}
                disabled={bulkLoading}
                className="text-blue-700 hover:underline disabled:opacity-50"
              >
                Aktivieren
              </button>
              <button
                onClick={() => handleBulk("deactivate")}
                disabled={bulkLoading}
                className="text-red-600 hover:underline disabled:opacity-50"
              >
                Deaktivieren
              </button>
              <button onClick={() => setSelected(new Set())} className="text-gray-400 hover:text-gray-700">
                <X size={14} />
              </button>
            </div>
          )}
        </div>

        {/* Table */}
        {loading ? (
          <div className="flex justify-center py-20">
            <Loader2 size={24} className="animate-spin text-blue-500" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-20 text-gray-400">
            <Users size={36} />
            <p className="text-sm">Noch keine Worker. Kandidaten über den Button oben aktivieren.</p>
          </div>
        ) : (
          <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  <th className="w-10 px-4 py-3">
                    <button onClick={toggleAll} className="text-gray-400 hover:text-gray-700">
                      {allSelected
                        ? <CheckSquare size={16} className="text-blue-600" />
                        : <Square size={16} />
                      }
                    </button>
                  </th>
                  <th className="px-4 py-3">Worker</th>
                  <th className="px-4 py-3 hidden sm:table-cell">Beschäftigung</th>
                  <th className="px-4 py-3 hidden md:table-cell">Module</th>
                  <th className="px-4 py-3 hidden md:table-cell">Manager</th>
                  <th className="px-4 py-3 hidden lg:table-cell">Team</th>
                  <th className="px-4 py-3 text-center">Status</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((w) => {
                  const isChecked = selected.has(w.id);
                  const isActive = w.settings?.is_active ?? false;
                  return (
                    <tr
                      key={w.id}
                      className={`transition-colors ${isChecked ? "bg-blue-50/50" : "hover:bg-gray-50/50"}`}
                    >
                      <td className="px-4 py-3">
                        <button onClick={() => toggleSelect(w.id)} className="text-gray-400 hover:text-gray-700">
                          {isChecked
                            ? <CheckSquare size={16} className="text-blue-600" />
                            : <Square size={16} />
                          }
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-semibold text-gray-600">
                            {(w.full_name ?? w.email)[0].toUpperCase()}
                          </span>
                          <div className="min-w-0">
                            <p className="font-medium text-gray-900 truncate">{w.full_name ?? "—"}</p>
                            <p className="text-xs text-gray-400 truncate">{w.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell">
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                          {EMPLOYMENT_LABELS[w.employment_type ?? "temp"] ?? w.employment_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 hidden md:table-cell">
                        <span className="text-gray-600">
                          {w.modules_enabled} / {Object.keys(MODULE_LABELS).length}
                        </span>
                      </td>
                      <td className="px-4 py-3 hidden md:table-cell text-gray-500 text-xs">
                        {w.manager?.full_name ?? w.manager?.email ?? "—"}
                      </td>
                      <td className="px-4 py-3 hidden lg:table-cell">
                        {w.team ? (
                          <span className="rounded-full bg-blue-50 text-blue-700 px-2 py-0.5 text-xs font-medium">
                            {w.team.name}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleToggleActive(w)}
                          title={isActive ? "Deaktivieren" : "Aktivieren"}
                          className="transition-colors"
                        >
                          {isActive
                            ? <ToggleRight size={22} className="text-blue-500" />
                            : <ToggleLeft size={22} className="text-gray-300" />
                          }
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => setDrawer({ mode: "settings", worker: w })}
                          className="rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:border-gray-300 hover:text-gray-900 transition-colors whitespace-nowrap"
                        >
                          Einstellungen
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {/* Settings drawer + Activate drawer */}
      {drawer.mode === "settings" && (
        <WorkerSettingsDrawer
          worker={drawer.worker}
          token={token}
          teams={teams}
          onClose={() => setDrawer({ mode: "closed" })}
          onSaved={(updated) => {
            setWorkers((prev) => prev.map((w) => w.id === updated.id ? updated : w));
            setDrawer({ mode: "closed" });
          }}
        />
      )}

      {drawer.mode === "activate" && (
        <ActivateWorkerDrawer
          token={token}
          onClose={() => setDrawer({ mode: "closed" })}
          onActivated={(newWorker) => {
            setWorkers((prev) => [newWorker, ...prev]);
            setDrawer({ mode: "closed" });
          }}
        />
      )}
    </div>
  );
}


// ── Settings Drawer ────────────────────────────────────────────────────────────

function WorkerSettingsDrawer({
  worker,
  token,
  teams,
  onClose,
  onSaved,
}: {
  worker: WorkerListRead;
  token: string;
  teams: TeamRead[];
  onClose: () => void;
  onSaved: (w: WorkerListRead) => void;
}) {
  const s = worker.settings;
  const [employmentType, setEmploymentType] = useState(s?.employment_type ?? "temp");
  const [maxHours, setMaxHours] = useState<string>(s?.max_weekly_hours?.toString() ?? "");
  const [internalNote, setInternalNote] = useState(s?.internal_note ?? "");
  const [assignedTeamId, setAssignedTeamId] = useState<string>(s?.assigned_team_id ?? "");
  const [modules, setModules] = useState<Record<string, boolean>>(
    s?.active_modules ?? Object.fromEntries(Object.keys(MODULE_LABELS).map((k) => [k, true]))
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleModule(key: string) {
    setModules((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await workerManagementApi.updateSettings(token, worker.id, {
        employment_type: employmentType,
        max_weekly_hours: maxHours ? parseInt(maxHours) : undefined,
        internal_note: internalNote || undefined,
        active_modules: modules as WorkerSettingsUpdate["active_modules"],
        assigned_team_id: assignedTeamId || null,
      });
      // Re-fetch this worker to get fresh data
      const updated = await workerManagementApi.get(token, worker.id);
      onSaved(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Fehler beim Speichern.");
    } finally {
      setSaving(false);
    }
  }

  const enabledCount = Object.values(modules).filter(Boolean).length;

  return (
    <Drawer title={`Einstellungen: ${worker.full_name ?? worker.email}`} onClose={onClose}>
      <div className="space-y-6">

        {/* Employment type */}
        <div className="space-y-1.5">
          <Label className="text-xs">Beschäftigungsart</Label>
          <select
            value={employmentType}
            onChange={(e) => setEmploymentType(e.target.value)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {Object.entries(EMPLOYMENT_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>

        {/* Team assignment */}
        {teams.length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-xs">Team</Label>
            <select
              value={assignedTeamId}
              onChange={(e) => setAssignedTeamId(e.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">— Kein Team —</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
        )}

        {/* Max weekly hours */}
        <div className="space-y-1.5">
          <Label className="text-xs">Max. Stunden / Woche</Label>
          <Input
            type="number"
            min={1}
            max={60}
            value={maxHours}
            onChange={(e) => setMaxHours(e.target.value)}
            placeholder="z.B. 40"
            className="text-sm"
          />
        </div>

        {/* Module toggles */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs">Aktive Module</Label>
            <span className="text-xs text-gray-400">{enabledCount} / {Object.keys(MODULE_LABELS).length}</span>
          </div>
          <div className="rounded-lg border border-gray-100 divide-y divide-gray-100">
            {Object.entries(MODULE_LABELS).map(([key, label]) => (
              <label key={key} className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50">
                <span className="text-sm text-gray-700">{label}</span>
                <button
                  type="button"
                  onClick={() => toggleModule(key)}
                  className="transition-colors"
                  aria-label={modules[key] ? "Deaktivieren" : "Aktivieren"}
                >
                  {modules[key]
                    ? <ToggleRight size={22} className="text-blue-500" />
                    : <ToggleLeft size={22} className="text-gray-300" />
                  }
                </button>
              </label>
            ))}
          </div>
        </div>

        {/* Internal note */}
        <div className="space-y-1.5">
          <Label className="text-xs">Interne Notiz (nur HR)</Label>
          <textarea
            rows={3}
            value={internalNote}
            onChange={(e) => setInternalNote(e.target.value)}
            placeholder="Nur für Recruiter sichtbar…"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        {error && (
          <p className="flex items-center gap-1.5 text-sm text-red-600">
            <AlertCircle size={14} /> {error}
          </p>
        )}

        <Button onClick={handleSave} disabled={saving} className="w-full flex items-center gap-2">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? "Wird gespeichert…" : "Speichern"}
        </Button>
      </div>
    </Drawer>
  );
}


// ── Activate Worker Drawer ────────────────────────────────────────────────────

function ActivateWorkerDrawer({
  token,
  onClose,
  onActivated,
}: {
  token: string;
  onClose: () => void;
  onActivated: (w: WorkerListRead) => void;
}) {
  const [email, setEmail] = useState("");
  const [employmentType, setEmploymentType] = useState("temp");
  const [loading, setLoading] = useState(false);
  const [searchResult, setSearchResult] = useState<{ id: string; email: string; full_name: string | null } | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch() {
    if (!email.trim()) return;
    setLoading(true);
    setNotFound(false);
    setSearchResult(null);
    setError(null);
    try {
      const me = await workerManagementApi.searchCandidate(token, email.trim());
      setSearchResult(me);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true);
      else setError("Suche fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  async function handleActivate() {
    if (!searchResult) return;
    setLoading(true);
    setError(null);
    try {
      const worker = await workerManagementApi.activate(token, {
        user_id: searchResult.id,
        employment_type: employmentType,
      });
      onActivated(worker);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Aktivierung fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Drawer title="Kandidat als Worker aktivieren" onClose={onClose}>
      <div className="space-y-5">
        <p className="text-sm text-gray-500">
          Suche einen registrierten Kandidaten und aktiviere seinen Worker-Portal-Zugang.
        </p>

        {/* Email search */}
        <div className="space-y-1.5">
          <Label className="text-xs">E-Mail des Kandidaten</Label>
          <div className="flex gap-2">
            <Input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="kandidat@beispiel.de"
              className="text-sm flex-1"
            />
            <Button variant="outline" onClick={handleSearch} disabled={loading} size="sm">
              {loading ? <Loader2 size={14} className="animate-spin" /> : "Suchen"}
            </Button>
          </div>
          {notFound && <p className="text-xs text-red-500">Kein Nutzer mit dieser E-Mail gefunden.</p>}
        </div>

        {/* Found user */}
        {searchResult && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 flex items-center gap-3">
            <UserCheck size={18} className="text-blue-600 shrink-0" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-900">{searchResult.full_name ?? searchResult.email}</p>
              <p className="text-xs text-gray-500">{searchResult.email}</p>
            </div>
          </div>
        )}

        {/* Employment type */}
        <div className="space-y-1.5">
          <Label className="text-xs">Beschäftigungsart</Label>
          <select
            value={employmentType}
            onChange={(e) => setEmploymentType(e.target.value)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {Object.entries(EMPLOYMENT_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>

        {error && (
          <p className="flex items-center gap-1.5 text-sm text-red-600">
            <AlertCircle size={14} /> {error}
          </p>
        )}

        <Button
          onClick={handleActivate}
          disabled={!searchResult || loading}
          className="w-full flex items-center gap-2"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
          Als Worker aktivieren
        </Button>
      </div>
    </Drawer>
  );
}


// ── Shared Drawer shell ───────────────────────────────────────────────────────

function Drawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-[1px]"
        onClick={onClose}
      />
      {/* Panel */}
      <aside className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-gray-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-5">{children}</div>
      </aside>
    </>
  );
}
