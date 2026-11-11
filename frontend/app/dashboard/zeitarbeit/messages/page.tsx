"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  MessageSquare,
  Send,
  ChevronLeft,
  Clock,
  CheckCircle2,
  AlertCircle,
  User,
  Lock,
  Unlock,
  CheckCheck,
  RotateCcw,
  Users,
  Filter,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { hrMessagesApi, teamsApi, ThreadRead, ThreadWithMessages, MessageRead, TeamRead } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffDays === 0) return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (diffDays === 1) return "Gestern";
  if (diffDays < 7) return d.toLocaleDateString("de-DE", { weekday: "short" });
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}

const STATUS_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  open:        { label: "Offen",          color: "text-blue-600 bg-blue-50",   icon: <Clock className="w-3 h-3" /> },
  in_progress: { label: "In Bearbeitung", color: "text-amber-600 bg-amber-50", icon: <AlertCircle className="w-3 h-3" /> },
  resolved:    { label: "Gelöst",         color: "text-green-600 bg-green-50", icon: <CheckCircle2 className="w-3 h-3" /> },
};

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? STATUS_META.open;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>
      {m.icon}{m.label}
    </span>
  );
}

// ── Thread List Item ──────────────────────────────────────────────────────────

function ThreadItem({
  thread,
  active,
  onClick,
}: {
  thread: ThreadRead;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full px-4 py-3 text-left border-b border-gray-50 hover:bg-gray-50 transition-colors ${
        active ? "bg-blue-50 border-l-2 border-l-blue-500" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="flex items-center gap-1.5 min-w-0">
          {thread.unread_hr > 0 && (
            <span className="w-2 h-2 bg-blue-500 rounded-full flex-shrink-0" />
          )}
          <p className="text-sm font-medium text-gray-900 truncate">{thread.worker_name ?? thread.worker_email}</p>
        </div>
        <span className="text-xs text-gray-400 flex-shrink-0">
          {thread.last_message_at ? fmtTime(thread.last_message_at) : ""}
        </span>
      </div>
      <p className="text-xs text-gray-600 font-medium truncate mb-1">{thread.subject}</p>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-gray-400 truncate flex-1">{thread.preview}</p>
        <StatusBadge status={thread.status} />
      </div>
      {thread.claimed_by_name && (
        <p className="text-xs text-gray-400 mt-1 flex items-center gap-1">
          <User className="w-3 h-3" />{thread.claimed_by_name}
        </p>
      )}
    </button>
  );
}

// ── Chat Panel ────────────────────────────────────────────────────────────────

function ChatPanel({
  thread,
  currentUserId,
  onBack,
  onAction,
  actionLoading,
}: {
  thread: ThreadWithMessages;
  currentUserId: string;
  onBack: () => void;
  onAction: (action: string, payload?: string) => void;
  actionLoading: boolean;
}) {
  const [replyText, setReplyText] = useState("");
  const [isInternal, setIsInternal] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread.messages]);

  function send() {
    if (!replyText.trim()) return;
    onAction(isInternal ? "internal_note" : "reply", replyText.trim());
    setReplyText("");
  }

  const isClaimed = !!thread.claimed_by;
  const isMyThread = thread.claimed_by === currentUserId;

  return (
    <div className="flex flex-col h-full">
      {/* Chat header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100 bg-white flex-shrink-0">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 md:hidden">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{thread.subject}</p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <User className="w-3 h-3" />
              {thread.worker_name ?? thread.worker_email}
            </span>
            {thread.assigned_team_name && (
              <span className="flex items-center gap-1 text-xs text-gray-400">
                <Users className="w-3 h-3" />
                {thread.assigned_team_name}
              </span>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1">
          <StatusBadge status={thread.status} />

          {/* Claim / Unclaim */}
          {!isClaimed ? (
            <button
              disabled={actionLoading}
              onClick={() => onAction("claim")}
              title="Übernehmen"
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100 disabled:opacity-40"
            >
              <Lock className="w-3.5 h-3.5" />
              Übernehmen
            </button>
          ) : isMyThread ? (
            <button
              disabled={actionLoading}
              onClick={() => onAction("unclaim")}
              title="Freigeben"
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-40"
            >
              <Unlock className="w-3.5 h-3.5" />
              Freigeben
            </button>
          ) : (
            <span className="text-xs text-gray-400 px-2">
              {thread.claimed_by_name}
            </span>
          )}

          {/* Resolve / Reopen */}
          {thread.status !== "resolved" ? (
            <button
              disabled={actionLoading}
              onClick={() => onAction("resolve")}
              title="Als gelöst markieren"
              className="p-1.5 rounded-lg text-green-600 hover:bg-green-50 disabled:opacity-40"
            >
              <CheckCheck className="w-4 h-4" />
            </button>
          ) : (
            <button
              disabled={actionLoading}
              onClick={() => onAction("reopen")}
              title="Wieder öffnen"
              className="p-1.5 rounded-lg text-amber-600 hover:bg-amber-50 disabled:opacity-40"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-gray-50">
        {thread.messages.map((msg) => {
          const isMe = msg.sender_id === currentUserId;
          const isWorker = msg.sender_role === "worker";

          if (msg.is_internal_note) {
            return (
              <div key={msg.id} className="flex justify-center">
                <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5 max-w-[85%]">
                  <p className="text-xs font-medium text-amber-700 mb-1 flex items-center gap-1">
                    <Lock className="w-3 h-3" />
                    Interne Notiz – {msg.sender_name}
                  </p>
                  <p className="text-sm text-amber-900 whitespace-pre-wrap">{msg.body}</p>
                  <p className="text-xs text-amber-500 mt-1 text-right">{fmtTime(msg.created_at)}</p>
                </div>
              </div>
            );
          }

          return (
            <div key={msg.id} className={`flex ${isWorker ? "justify-start" : "justify-end"}`}>
              <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
                isWorker
                  ? "bg-white border border-gray-200 text-gray-900 rounded-bl-sm"
                  : "bg-blue-600 text-white rounded-br-sm"
              }`}>
                {isWorker && (
                  <p className="text-xs font-medium mb-1 text-gray-500">{msg.sender_name}</p>
                )}
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.body}</p>
                <p className={`text-xs mt-1 ${isWorker ? "text-gray-400" : "text-blue-200"} text-right`}>
                  {fmtTime(msg.created_at)}
                </p>
              </div>
            </div>
          );
        })}

        {thread.messages.length === 0 && (
          <p className="text-center text-sm text-gray-400 py-8">Noch keine Nachrichten</p>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Reply + internal note input */}
      <div className="px-4 py-3 border-t border-gray-100 bg-white flex-shrink-0">
        {/* Toggle: reply vs. internal note */}
        <div className="flex gap-2 mb-2">
          <button
            onClick={() => setIsInternal(false)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
              !isInternal ? "bg-blue-600 text-white" : "text-gray-500 hover:bg-gray-100"
            }`}
          >
            <Send className="w-3 h-3" />
            Antwort
          </button>
          <button
            onClick={() => setIsInternal(true)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
              isInternal ? "bg-amber-500 text-white" : "text-gray-500 hover:bg-gray-100"
            }`}
          >
            <Lock className="w-3 h-3" />
            Interne Notiz
          </button>
        </div>

        <div className="flex items-end gap-2">
          <textarea
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder={isInternal ? "Interne Notiz (nur HR sichtbar)..." : "Antwort an Mitarbeiter..."}
            rows={2}
            className={`flex-1 border rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 ${
              isInternal
                ? "border-amber-300 bg-amber-50 focus:ring-amber-400"
                : "border-gray-300 focus:ring-blue-500"
            }`}
          />
          <button
            disabled={!replyText.trim() || actionLoading}
            onClick={send}
            className={`p-2.5 text-white rounded-xl disabled:opacity-40 flex-shrink-0 ${
              isInternal ? "bg-amber-500 hover:bg-amber-600" : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function HRMessagesPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState("");

  const [threads, setThreads] = useState<ThreadRead[]>([]);
  const [teams, setTeams] = useState<TeamRead[]>([]);
  const [activeThread, setActiveThread] = useState<ThreadWithMessages | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  // Filters
  const [statusFilter, setStatusFilter] = useState("open");
  const [teamFilter, setTeamFilter] = useState("all");
  const [unreadOnly, setUnreadOnly] = useState(false);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
    try {
      const payload = JSON.parse(atob(t.split(".")[1]));
      setUserId(payload.sub ?? "");
    } catch { /* ignore */ }
  }, [router]);

  const loadThreads = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const [ts, teamList] = await Promise.all([
        hrMessagesApi.list(t, {
          status: statusFilter !== "all" ? statusFilter : undefined,
          team_id: teamFilter !== "all" ? teamFilter : undefined,
          unread_only: unreadOnly,
        }),
        teamsApi.list(t).catch(() => [] as TeamRead[]),
      ]);
      setThreads(ts);
      setTeams(teamList);
    } catch {
      setThreads([]);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, teamFilter, unreadOnly]);

  useEffect(() => {
    if (token) loadThreads(token);
  }, [token, loadThreads]);

  async function openThread(thread: ThreadRead) {
    if (!token) return;
    try {
      const full = await hrMessagesApi.get(token, thread.id);
      setActiveThread(full);
      setThreads((prev) => prev.map((t) => t.id === thread.id ? { ...t, unread_hr: 0 } : t));
    } catch { /* ignore */ }
  }

  async function handleAction(action: string, payload?: string) {
    if (!token || !activeThread) return;
    setActionLoading(true);
    try {
      let updated: ThreadRead | ThreadWithMessages | undefined;

      if (action === "reply") {
        const msg = await hrMessagesApi.reply(token, activeThread.id, payload!, false);
        setActiveThread((prev) => prev ? { ...prev, messages: [...prev.messages, msg], status: prev.status === "open" ? "in_progress" : prev.status } : prev);
        setActionLoading(false);
        return;
      }
      if (action === "internal_note") {
        const msg = await hrMessagesApi.reply(token, activeThread.id, payload!, true);
        setActiveThread((prev) => prev ? { ...prev, messages: [...prev.messages, msg] } : prev);
        setActionLoading(false);
        return;
      }
      if (action === "claim") updated = await hrMessagesApi.claim(token, activeThread.id);
      if (action === "unclaim") updated = await hrMessagesApi.unclaim(token, activeThread.id);
      if (action === "resolve") updated = await hrMessagesApi.resolve(token, activeThread.id);
      if (action === "reopen") updated = await hrMessagesApi.reopen(token, activeThread.id);

      if (updated) {
        setActiveThread((prev) => prev ? { ...prev, ...updated } : prev);
        setThreads((prev) => prev.map((t) => t.id === activeThread.id ? { ...t, ...updated } : t));
      }
    } catch { /* ignore */ }
    finally { setActionLoading(false); }
  }

  const totalUnread = threads.reduce((s, t) => s + t.unread_hr, 0);

  return (
    <div className="flex h-[calc(100vh-56px)] bg-white">
      {/* Left: thread list */}
      <div className={`flex flex-col border-r border-gray-100 w-full md:w-80 lg:w-96 flex-shrink-0 ${activeThread ? "hidden md:flex" : "flex"}`}>

        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-100">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className="text-base font-semibold text-gray-900">Nachrichten-Inbox</h1>
              {totalUnread > 0 && (
                <p className="text-xs text-blue-600">{totalUnread} ungelesen</p>
              )}
            </div>
          </div>

          {/* Filters */}
          <div className="flex flex-col gap-2">
            <div className="flex gap-2">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="all">Alle Status</option>
                <option value="open">Offen</option>
                <option value="in_progress">In Bearbeitung</option>
                <option value="resolved">Gelöst</option>
              </select>
              {teams.length > 0 && (
                <select
                  value={teamFilter}
                  onChange={(e) => setTeamFilter(e.target.value)}
                  className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="all">Alle Teams</option>
                  {teams.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              )}
            </div>
            <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(e) => setUnreadOnly(e.target.checked)}
                className="rounded border-gray-300 text-blue-600"
              />
              Nur ungelesene
            </label>
          </div>
        </div>

        {/* Thread list */}
        {loading ? (
          <div className="flex items-center justify-center h-32 text-gray-400 text-sm gap-2">
            <div className="w-4 h-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
            Lade...
          </div>
        ) : threads.length === 0 ? (
          <div className="flex flex-col items-center justify-center flex-1 text-gray-400 gap-2 p-6">
            <MessageSquare className="w-10 h-10 text-gray-200" />
            <p className="text-sm">Keine Konversationen</p>
          </div>
        ) : (
          <div className="overflow-y-auto flex-1">
            {threads.map((t) => (
              <ThreadItem
                key={t.id}
                thread={t}
                active={activeThread?.id === t.id}
                onClick={() => openThread(t)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Right: chat panel */}
      <div className={`flex-1 ${activeThread ? "flex" : "hidden md:flex"} flex-col`}>
        {activeThread ? (
          <ChatPanel
            thread={activeThread}
            currentUserId={userId}
            onBack={() => setActiveThread(null)}
            onAction={handleAction}
            actionLoading={actionLoading}
          />
        ) : (
          <div className="flex flex-col items-center justify-center flex-1 text-gray-400 gap-3">
            <MessageSquare className="w-12 h-12 text-gray-200" />
            <p className="text-sm">Konversation auswählen</p>
          </div>
        )}
      </div>
    </div>
  );
}
