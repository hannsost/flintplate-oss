"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  MessageSquare,
  Plus,
  Send,
  X,
  ChevronLeft,
  Clock,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { workerMessagesApi, ThreadRead, ThreadWithMessages, MessageRead } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
  if (diffDays === 0) return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (diffDays === 1) return "Gestern";
  if (diffDays < 7) return d.toLocaleDateString("de-DE", { weekday: "short" });
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}

const STATUS_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  open:        { label: "Offen",          color: "text-blue-600 bg-blue-50",    icon: <Clock className="w-3 h-3" /> },
  in_progress: { label: "In Bearbeitung", color: "text-amber-600 bg-amber-50",  icon: <AlertCircle className="w-3 h-3" /> },
  resolved:    { label: "Gelöst",         color: "text-green-600 bg-green-50",  icon: <CheckCircle2 className="w-3 h-3" /> },
};

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? STATUS_META.open;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>
      {m.icon}{m.label}
    </span>
  );
}

// ── New Thread Sheet ──────────────────────────────────────────────────────────

function NewThreadSheet({
  onSend,
  onClose,
  sending,
}: {
  onSend: (subject: string, body: string) => void;
  onClose: () => void;
  sending: boolean;
}) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed inset-x-0 bottom-0 z-50 bg-white rounded-t-2xl shadow-2xl p-5 pb-8 md:inset-auto md:top-1/2 md:left-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:w-full md:max-w-lg md:rounded-2xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">Neue Nachricht</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-3">
          <input
            type="text"
            placeholder="Betreff"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <textarea
            placeholder="Deine Nachricht..."
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={5}
            className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-gray-600 bg-gray-100 rounded-xl hover:bg-gray-200">
            Abbrechen
          </button>
          <button
            disabled={!subject.trim() || !body.trim() || sending}
            onClick={() => onSend(subject.trim(), body.trim())}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 text-sm text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-40"
          >
            <Send className="w-3.5 h-3.5" />
            {sending ? "Senden..." : "Senden"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Chat View ─────────────────────────────────────────────────────────────────

function ChatView({
  thread,
  userId,
  onBack,
  onReply,
  replying,
}: {
  thread: ThreadWithMessages;
  userId: string;
  onBack: () => void;
  onReply: (body: string) => void;
  replying: boolean;
}) {
  const [replyText, setReplyText] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread.messages]);

  function send() {
    if (!replyText.trim()) return;
    onReply(replyText.trim());
    setReplyText("");
  }

  return (
    <div className="flex flex-col h-full">
      {/* Chat header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100 bg-white">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 md:hidden">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{thread.subject}</p>
          {thread.assigned_team_name && (
            <p className="text-xs text-gray-400">Team: {thread.assigned_team_name}</p>
          )}
        </div>
        <StatusBadge status={thread.status} />
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {thread.messages.map((msg) => {
          const isMe = msg.sender_id === userId;
          return (
            <div key={msg.id} className={`flex ${isMe ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
                isMe
                  ? "bg-blue-600 text-white rounded-br-sm"
                  : "bg-gray-100 text-gray-900 rounded-bl-sm"
              }`}>
                {!isMe && (
                  <p className="text-xs font-medium mb-1 opacity-70">{msg.sender_name}</p>
                )}
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.body}</p>
                <p className={`text-xs mt-1 ${isMe ? "text-blue-200" : "text-gray-400"} text-right`}>
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

      {/* Reply input */}
      {thread.status !== "resolved" ? (
        <div className="px-4 py-3 border-t border-gray-100 bg-white">
          <div className="flex items-end gap-2">
            <textarea
              value={replyText}
              onChange={(e) => setReplyText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Antwort schreiben... (Enter = Senden)"
              rows={2}
              className="flex-1 border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              disabled={!replyText.trim() || replying}
              onClick={send}
              className="p-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-40 flex-shrink-0"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      ) : (
        <div className="px-4 py-3 border-t border-gray-100 bg-gray-50 text-center text-sm text-gray-400">
          Diese Konversation wurde gelöst. Schreibe eine neue Nachricht um sie wieder zu öffnen.
        </div>
      )}
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function WorkerMessagesPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState("");

  const [threads, setThreads] = useState<ThreadRead[]>([]);
  const [activeThread, setActiveThread] = useState<ThreadWithMessages | null>(null);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);

    // Get userId from token payload
    try {
      const payload = JSON.parse(atob(t.split(".")[1]));
      setUserId(payload.sub ?? "");
    } catch { /* ignore */ }
  }, [router]);

  const loadThreads = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const data = await workerMessagesApi.list(t);
      setThreads(data);
    } catch {
      setThreads([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (token) loadThreads(token);
  }, [token, loadThreads]);

  async function openThread(thread: ThreadRead) {
    if (!token) return;
    try {
      const full = await workerMessagesApi.get(token, thread.id);
      setActiveThread(full);
      // Update unread count in list
      setThreads((prev) => prev.map((t) => t.id === thread.id ? { ...t, unread_worker: 0 } : t));
    } catch { /* ignore */ }
  }

  async function handleNewThread(subject: string, body: string) {
    if (!token) return;
    setSending(true);
    try {
      const thread = await workerMessagesApi.create(token, { subject, body });
      setShowNew(false);
      setThreads((prev) => [thread, ...prev]);
      setActiveThread(thread);
    } catch { /* ignore */ }
    finally { setSending(false); }
  }

  async function handleReply(body: string) {
    if (!token || !activeThread) return;
    setSending(true);
    try {
      const msg = await workerMessagesApi.reply(token, activeThread.id, body);
      setActiveThread((prev) => prev ? {
        ...prev,
        messages: [...prev.messages, msg],
        status: prev.status === "resolved" ? "open" : prev.status,
      } : prev);
      setThreads((prev) => prev.map((t) => t.id === activeThread.id
        ? { ...t, last_message_at: msg.created_at }
        : t
      ));
    } catch { /* ignore */ }
    finally { setSending(false); }
  }

  return (
    <div className="flex h-[calc(100vh-56px)] bg-white">
      {/* Thread list panel */}
      <div className={`flex flex-col border-r border-gray-100 w-full md:w-80 flex-shrink-0 ${activeThread ? "hidden md:flex" : "flex"}`}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <h1 className="text-base font-semibold text-gray-900">Nachrichten</h1>
          <button
            onClick={() => setShowNew(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700"
          >
            <Plus className="w-3.5 h-3.5" />
            Neu
          </button>
        </div>

        {/* Thread list */}
        {loading ? (
          <div className="flex items-center justify-center h-32 text-gray-400 text-sm">Lade...</div>
        ) : threads.length === 0 ? (
          <div className="flex flex-col items-center justify-center flex-1 text-gray-400 gap-3 p-6">
            <MessageSquare className="w-10 h-10 text-gray-200" />
            <p className="text-sm text-center">Noch keine Nachrichten.<br />Schreib deinem HR-Team.</p>
            <button
              onClick={() => setShowNew(true)}
              className="text-sm text-blue-600 hover:underline"
            >
              Erste Nachricht schreiben
            </button>
          </div>
        ) : (
          <div className="overflow-y-auto flex-1">
            {threads.map((t) => (
              <button
                key={t.id}
                onClick={() => openThread(t)}
                className={`w-full px-4 py-3 text-left border-b border-gray-50 hover:bg-gray-50 transition-colors ${
                  activeThread?.id === t.id ? "bg-blue-50" : ""
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-gray-900 truncate flex-1">{t.subject}</p>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {t.unread_worker > 0 && (
                      <span className="w-2 h-2 bg-blue-500 rounded-full" />
                    )}
                    <span className="text-xs text-gray-400">
                      {t.last_message_at ? fmtTime(t.last_message_at) : ""}
                    </span>
                  </div>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <p className="text-xs text-gray-400 truncate flex-1">{t.preview}</p>
                  <StatusBadge status={t.status} />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Chat panel */}
      <div className={`flex-1 ${activeThread ? "flex" : "hidden md:flex"} flex-col`}>
        {activeThread ? (
          <ChatView
            thread={activeThread}
            userId={userId}
            onBack={() => setActiveThread(null)}
            onReply={handleReply}
            replying={sending}
          />
        ) : (
          <div className="flex flex-col items-center justify-center flex-1 text-gray-400 gap-3">
            <MessageSquare className="w-12 h-12 text-gray-200" />
            <p className="text-sm">Konversation auswählen</p>
          </div>
        )}
      </div>

      {showNew && (
        <NewThreadSheet
          onSend={handleNewThread}
          onClose={() => setShowNew(false)}
          sending={sending}
        />
      )}
    </div>
  );
}
