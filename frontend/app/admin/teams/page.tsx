"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  Users,
  Pencil,
  Trash2,
  X,
  UserPlus,
  Crown,
  Eye,
  ChevronDown,
  RefreshCw,
  Shield,
} from "lucide-react";
import { auth } from "@/lib/auth";
import {
  teamsApi,
  TeamRead,
  TeamWithMembers,
  TeamMemberRead,
  TeamCreate,
  WorkerListRead,
  workerManagementApi,
} from "@/lib/api";
import { authApi } from "@/lib/api";

// ── Role badges ───────────────────────────────────────────────────────────────

const ROLE_META = {
  lead:   { label: "Team Lead",  color: "bg-amber-100 text-amber-700",  icon: <Crown className="w-3 h-3" /> },
  member: { label: "Mitglied",   color: "bg-blue-100 text-blue-700",    icon: <Users className="w-3 h-3" /> },
  viewer: { label: "Beobachter", color: "bg-gray-100 text-gray-600",    icon: <Eye className="w-3 h-3" /> },
};

function RoleBadge({ role }: { role: string }) {
  const meta = ROLE_META[role as keyof typeof ROLE_META] ?? ROLE_META.member;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${meta.color}`}>
      {meta.icon}
      {meta.label}
    </span>
  );
}

// ── Team Card ─────────────────────────────────────────────────────────────────

function TeamCard({
  team,
  onSelect,
  onDelete,
  selected,
}: {
  team: TeamRead;
  onSelect: () => void;
  onDelete: () => void;
  selected: boolean;
}) {
  return (
    <div
      onClick={onSelect}
      className={`bg-white border rounded-xl p-4 cursor-pointer transition-all hover:shadow-sm ${
        selected ? "border-blue-500 ring-2 ring-blue-100" : "border-gray-200"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0">
              <Shield className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-900 truncate">{team.name}</p>
              {team.description && (
                <p className="text-xs text-gray-400 truncate">{team.description}</p>
              )}
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <Users className="w-3.5 h-3.5" />
              {team.member_count} {team.member_count === 1 ? "Mitglied" : "Mitglieder"}
            </span>
            {!team.is_active && (
              <span className="text-xs text-red-500">Inaktiv</span>
            )}
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="p-1.5 rounded-lg text-gray-300 hover:text-red-500 hover:bg-red-50"
          title="Team löschen"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Create Team Dialog ────────────────────────────────────────────────────────

function CreateTeamDialog({
  onConfirm,
  onCancel,
  saving,
}: {
  onConfirm: (data: TeamCreate) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-base font-semibold text-gray-900 mb-4">Neues Team erstellen</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="z. B. München Automotive"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Beschreibung</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Optional..."
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <div className="flex gap-2 mt-5">
          <button onClick={onCancel} className="flex-1 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">
            Abbrechen
          </button>
          <button
            disabled={!name.trim() || saving}
            onClick={() => onConfirm({ name: name.trim(), description: description.trim() || undefined })}
            className="flex-1 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40"
          >
            {saving ? "Erstelle..." : "Erstellen"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Add Member Dialog ─────────────────────────────────────────────────────────

function AddMemberDialog({
  recruiters,
  existingMemberIds,
  onConfirm,
  onCancel,
  saving,
}: {
  recruiters: { id: string; full_name: string | null; email: string }[];
  existingMemberIds: Set<string>;
  onConfirm: (userId: string, role: string) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("member");
  const available = recruiters.filter((r) => !existingMemberIds.has(r.id));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-base font-semibold text-gray-900 mb-4">Mitglied hinzufügen</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Benutzer *</label>
            <select
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">— Benutzer auswählen —</option>
              {available.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.full_name ?? r.email}
                </option>
              ))}
            </select>
            {available.length === 0 && (
              <p className="text-xs text-gray-400 mt-1">Alle Benutzer sind bereits Mitglied.</p>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Rolle</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="lead">Team Lead</option>
              <option value="member">Mitglied</option>
              <option value="viewer">Beobachter</option>
            </select>
          </div>
        </div>
        <div className="flex gap-2 mt-5">
          <button onClick={onCancel} className="flex-1 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">
            Abbrechen
          </button>
          <button
            disabled={!userId || saving}
            onClick={() => onConfirm(userId, role)}
            className="flex-1 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40"
          >
            {saving ? "Hinzufügen..." : "Hinzufügen"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function TeamsAdminPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);

  const [teams, setTeams] = useState<TeamRead[]>([]);
  const [selectedTeam, setSelectedTeam] = useState<TeamWithMembers | null>(null);
  const [recruiters, setRecruiters] = useState<{ id: string; full_name: string | null; email: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  // Dialogs
  const [showCreate, setShowCreate] = useState(false);
  const [showAddMember, setShowAddMember] = useState(false);
  const [saving, setSaving] = useState(false);

  // Auth + initial load
  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const loadTeams = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const [ts, users] = await Promise.all([
        teamsApi.list(t),
        authApi.listUsers ? authApi.listUsers(t) : Promise.resolve([]),
      ]);
      setTeams(ts);
      // Filter to recruiters/HR in tenant
      setRecruiters((users as { id: string; full_name: string | null; email: string; role: string }[])
        .filter((u) => u.role === "recruiter" || u.role === "admin")
        .map((u) => ({ id: u.id, full_name: u.full_name, email: u.email }))
      );
    } catch {
      setTeams([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (token) loadTeams(token);
  }, [token, loadTeams]);

  async function selectTeam(team: TeamRead) {
    if (!token) return;
    setDetailLoading(true);
    try {
      const detail = await teamsApi.get(token, team.id);
      setSelectedTeam(detail);
    } catch {
      setSelectedTeam(null);
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleCreateTeam(data: TeamCreate) {
    if (!token) return;
    setSaving(true);
    try {
      const created = await teamsApi.create(token, data);
      setShowCreate(false);
      await loadTeams(token);
      await selectTeam(created);
    } catch {
      // silently ignore
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteTeam(teamId: string) {
    if (!token || !confirm("Team wirklich deaktivieren?")) return;
    try {
      await teamsApi.delete(token, teamId);
      if (selectedTeam?.id === teamId) setSelectedTeam(null);
      await loadTeams(token);
    } catch {
      // silently ignore
    }
  }

  async function handleAddMember(userId: string, role: string) {
    if (!token || !selectedTeam) return;
    setSaving(true);
    try {
      await teamsApi.addMember(token, selectedTeam.id, { user_id: userId, role });
      setShowAddMember(false);
      const detail = await teamsApi.get(token, selectedTeam.id);
      setSelectedTeam(detail);
      await loadTeams(token);
    } catch {
      // silently ignore
    } finally {
      setSaving(false);
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!token || !selectedTeam || !confirm("Mitglied entfernen?")) return;
    try {
      await teamsApi.removeMember(token, selectedTeam.id, userId);
      const detail = await teamsApi.get(token, selectedTeam.id);
      setSelectedTeam(detail);
      await loadTeams(token);
    } catch {
      // silently ignore
    }
  }

  async function handleChangeRole(userId: string, role: string) {
    if (!token || !selectedTeam) return;
    try {
      await teamsApi.updateMemberRole(token, selectedTeam.id, userId, role);
      const detail = await teamsApi.get(token, selectedTeam.id);
      setSelectedTeam(detail);
    } catch {
      // silently ignore
    }
  }

  const existingMemberIds = new Set(selectedTeam?.members.map((m) => m.user_id) ?? []);

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Team-Verwaltung</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Teams erstellen, Mitglieder zuweisen und Rollen konfigurieren
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700 shadow-sm"
        >
          <Plus className="w-4 h-4" />
          Neues Team
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Left: Team list */}
        <div className="lg:col-span-1">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-medium text-gray-700">{teams.length} Teams</p>
            <button
              onClick={() => token && loadTeams(token)}
              disabled={loading}
              className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-32 text-gray-400 text-sm">
              Lade Teams...
            </div>
          ) : teams.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 text-gray-400 gap-2">
              <Shield className="w-8 h-8 text-gray-200" />
              <p className="text-sm">Noch keine Teams</p>
            </div>
          ) : (
            <div className="space-y-2">
              {teams.map((t) => (
                <TeamCard
                  key={t.id}
                  team={t}
                  selected={selectedTeam?.id === t.id}
                  onSelect={() => selectTeam(t)}
                  onDelete={() => handleDeleteTeam(t.id)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right: Team detail */}
        <div className="lg:col-span-2">
          {!selectedTeam ? (
            <div className="bg-white border border-gray-200 rounded-xl flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
              <Users className="w-10 h-10 text-gray-200" />
              <p className="text-sm">Team auswählen um Mitglieder zu verwalten</p>
            </div>
          ) : detailLoading ? (
            <div className="bg-white border border-gray-200 rounded-xl flex items-center justify-center h-64 text-gray-400 text-sm gap-2">
              <RefreshCw className="w-4 h-4 animate-spin" />
              Lade Team-Details...
            </div>
          ) : (
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              {/* Team header */}
              <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">{selectedTeam.name}</h2>
                  {selectedTeam.description && (
                    <p className="text-sm text-gray-500 mt-0.5">{selectedTeam.description}</p>
                  )}
                </div>
                <button
                  onClick={() => setShowAddMember(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  Hinzufügen
                </button>
              </div>

              {/* Members table */}
              {selectedTeam.members.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-32 text-gray-400 gap-2">
                  <Users className="w-8 h-8 text-gray-200" />
                  <p className="text-sm">Noch keine Mitglieder</p>
                </div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-50 bg-gray-50">
                      <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Benutzer</th>
                      <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Rolle</th>
                      <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Hinzugefügt</th>
                      <th className="px-5 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {selectedTeam.members.map((m) => (
                      <tr key={m.id} className="hover:bg-gray-50">
                        <td className="px-5 py-3">
                          <div>
                            <p className="text-sm font-medium text-gray-900">{m.full_name ?? "–"}</p>
                            <p className="text-xs text-gray-400">{m.email}</p>
                          </div>
                        </td>
                        <td className="px-5 py-3">
                          <select
                            value={m.role}
                            onChange={(e) => handleChangeRole(m.user_id, e.target.value)}
                            className="text-xs border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                          >
                            <option value="lead">Team Lead</option>
                            <option value="member">Mitglied</option>
                            <option value="viewer">Beobachter</option>
                          </select>
                        </td>
                        <td className="px-5 py-3 text-xs text-gray-500">
                          {new Date(m.joined_at).toLocaleDateString("de-DE")}
                        </td>
                        <td className="px-5 py-3 text-right">
                          <button
                            onClick={() => handleRemoveMember(m.user_id)}
                            className="p-1.5 rounded-lg text-gray-300 hover:text-red-500 hover:bg-red-50"
                            title="Entfernen"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Dialogs */}
      {showCreate && (
        <CreateTeamDialog
          onConfirm={handleCreateTeam}
          onCancel={() => setShowCreate(false)}
          saving={saving}
        />
      )}
      {showAddMember && selectedTeam && (
        <AddMemberDialog
          recruiters={recruiters}
          existingMemberIds={existingMemberIds as Set<string>}
          onConfirm={handleAddMember}
          onCancel={() => setShowAddMember(false)}
          saving={saving}
        />
      )}
    </div>
  );
}
