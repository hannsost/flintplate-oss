"use client";

import { useState } from "react";
import { Ticket, Plus, X, Send, Clock, CheckCircle2, AlertCircle, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// ── Demo data (static until backend is wired) ─────────────────────────────────

type TicketStatus = "open" | "in_progress" | "resolved";
type TicketPriority = "low" | "medium" | "high";

interface SupportTicket {
  id: string;
  subject: string;
  category: string;
  priority: TicketPriority;
  status: TicketStatus;
  message: string;
  created_at: string;
  updated_at: string;
  response?: string;
}

const DEMO_TICKETS: SupportTicket[] = [
  {
    id: "TKT-001",
    subject: "Lohnabrechnung März fehlt",
    category: "Lohnabrechnung",
    priority: "high",
    status: "in_progress",
    message: "Meine Lohnabrechnung für März wurde noch nicht hochgeladen. Können Sie das prüfen?",
    created_at: "2026-03-20T09:15:00",
    updated_at: "2026-03-21T14:30:00",
    response: "Vielen Dank für Ihre Anfrage. Wir prüfen das und melden uns bis Ende der Woche.",
  },
  {
    id: "TKT-002",
    subject: "Urlaubsantrag eingereicht",
    category: "Abwesenheit",
    priority: "medium",
    status: "resolved",
    message: "Ich möchte vom 15.04. bis 22.04.2026 Urlaub nehmen.",
    created_at: "2026-03-15T11:00:00",
    updated_at: "2026-03-16T09:00:00",
    response: "Ihr Urlaubsantrag wurde genehmigt. Schönen Urlaub!",
  },
];

const CATEGORIES = [
  "Lohnabrechnung",
  "Abwesenheit",
  "Einsatzplan",
  "Ausrüstung / Equipment",
  "Dokumente",
  "Zeiterfassung",
  "Sonstiges",
];

const PRIORITY_META: Record<TicketPriority, { label: string; color: string; bg: string }> = {
  low:    { label: "Niedrig", color: "text-gray-600",  bg: "bg-gray-100" },
  medium: { label: "Mittel",  color: "text-blue-600",  bg: "bg-blue-50" },
  high:   { label: "Hoch",    color: "text-red-600",   bg: "bg-red-50" },
};

const STATUS_META: Record<TicketStatus, { label: string; icon: React.ElementType; color: string }> = {
  open:        { label: "Offen",         icon: AlertCircle,  color: "text-amber-500" },
  in_progress: { label: "In Bearbeitung", icon: Clock,        color: "text-blue-500" },
  resolved:    { label: "Erledigt",      icon: CheckCircle2, color: "text-green-500" },
};

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// ── Ticket Card ───────────────────────────────────────────────────────────────

function TicketCard({ ticket }: { ticket: SupportTicket }) {
  const [expanded, setExpanded] = useState(false);
  const sm = STATUS_META[ticket.status];
  const pm = PRIORITY_META[ticket.priority];
  const Icon = sm.icon;

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <Icon size={16} className={`mt-0.5 shrink-0 ${sm.color}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-gray-900 truncate">{ticket.subject}</p>
            <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${pm.bg} ${pm.color}`}>
              {pm.label}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-0.5">
            <span className="text-xs text-gray-400">{ticket.id}</span>
            <span className="text-xs text-gray-400">{ticket.category}</span>
            <span className={`text-xs font-medium ${sm.color}`}>{sm.label}</span>
          </div>
        </div>
        <ChevronDown size={14} className={`shrink-0 text-gray-400 mt-0.5 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-gray-100">
          <div className="pt-3">
            <p className="text-xs text-gray-500 mb-1">Ihre Nachricht</p>
            <p className="text-sm text-gray-700">{ticket.message}</p>
          </div>
          {ticket.response && (
            <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2">
              <p className="text-xs font-medium text-blue-700 mb-1">Antwort vom HR-Team</p>
              <p className="text-sm text-blue-800">{ticket.response}</p>
            </div>
          )}
          <p className="text-xs text-gray-400">
            Erstellt: {fmtDate(ticket.created_at)} · Aktualisiert: {fmtDate(ticket.updated_at)}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TicketsPage() {
  const [tickets, setTickets] = useState<SupportTicket[]>(DEMO_TICKETS);
  const [showForm, setShowForm] = useState(false);
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("");
  const [priority, setPriority] = useState<TicketPriority>("medium");
  const [message, setMessage] = useState("");
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit() {
    if (!subject.trim() || !message.trim()) return;
    const newTicket: SupportTicket = {
      id: `TKT-${String(tickets.length + 1).padStart(3, "0")}`,
      subject: subject.trim(),
      category: category || "Sonstiges",
      priority,
      status: "open",
      message: message.trim(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    setTickets([newTicket, ...tickets]);
    setSubject("");
    setCategory("");
    setPriority("medium");
    setMessage("");
    setShowForm(false);
    setSubmitted(true);
    setTimeout(() => setSubmitted(false), 4000);
  }

  const open = tickets.filter((t) => t.status !== "resolved").length;

  return (
    <div className="min-h-screen bg-gray-50 p-4 pb-10">
      <div className="max-w-lg mx-auto space-y-4">

        {/* Header */}
        <div className="flex items-center justify-between pt-2">
          <div>
            <h1 className="text-xl font-bold text-gray-900 flex items-center gap-2">
              <Ticket size={20} className="text-blue-600" />
              Support-Tickets
            </h1>
            {open > 0 && (
              <p className="text-xs text-gray-500 mt-0.5">{open} offene Anfrage{open !== 1 ? "n" : ""}</p>
            )}
          </div>
          <Button
            size="sm"
            onClick={() => setShowForm(!showForm)}
            className="flex items-center gap-1.5"
          >
            {showForm ? <X size={14} /> : <Plus size={14} />}
            {showForm ? "Abbrechen" : "Neue Anfrage"}
          </Button>
        </div>

        {/* Success banner */}
        {submitted && (
          <div className="rounded-xl bg-green-50 border border-green-200 px-4 py-3 flex items-center gap-2 text-sm text-green-700">
            <CheckCircle2 size={16} />
            Ihre Anfrage wurde eingereicht. Das HR-Team meldet sich.
          </div>
        )}

        {/* New ticket form */}
        {showForm && (
          <div className="rounded-xl border border-blue-200 bg-white p-4 space-y-3">
            <h2 className="text-sm font-semibold text-gray-900">Neue Support-Anfrage</h2>

            <div className="space-y-1">
              <Label className="text-xs">Betreff *</Label>
              <Input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Kurze Beschreibung des Problems"
                className="text-sm"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Kategorie</Label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Bitte wählen</option>
                  {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>

              <div className="space-y-1">
                <Label className="text-xs">Priorität</Label>
                <select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as TicketPriority)}
                  className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="low">Niedrig</option>
                  <option value="medium">Mittel</option>
                  <option value="high">Hoch</option>
                </select>
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Nachricht *</Label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Beschreiben Sie Ihr Anliegen so genau wie möglich..."
                rows={4}
                className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            </div>

            <Button
              onClick={handleSubmit}
              disabled={!subject.trim() || !message.trim()}
              className="w-full flex items-center gap-2"
            >
              <Send size={14} />
              Anfrage absenden
            </Button>
          </div>
        )}

        {/* Ticket list */}
        {tickets.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-10 text-center">
            <Ticket size={32} className="mx-auto text-gray-300 mb-3" />
            <p className="text-sm font-medium text-gray-500">Keine Anfragen vorhanden</p>
            <p className="text-xs text-gray-400 mt-1">Erstellen Sie Ihre erste Support-Anfrage über den Button oben.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {tickets.map((t) => <TicketCard key={t.id} ticket={t} />)}
          </div>
        )}
      </div>
    </div>
  );
}
