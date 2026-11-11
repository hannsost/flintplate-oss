"use client";

import { useState } from "react";
import { Bug, Lightbulb, Palette, MessageCircle, X, Check, MessageSquare } from "lucide-react";
import { auth } from "@/lib/auth";

type Category = "bug" | "feature" | "general" | "ux";

const CATEGORIES: { value: Category; label: string; icon: React.ElementType }[] = [
  { value: "bug",     label: "Bug",       icon: Bug           },
  { value: "feature", label: "Wunsch",    icon: Lightbulb     },
  { value: "ux",      label: "UX/Design", icon: Palette       },
  { value: "general", label: "Allgemein", icon: MessageCircle },
];

export function FeedbackWidget() {
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<Category>("general");
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim() || message.length < 5) return;
    setSending(true);
    try {
      const token = auth.getAccess();
      await fetch("/api/feedback", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ category, message, page_url: window.location.pathname }),
      });
      setSent(true);
      setTimeout(() => { setOpen(false); setSent(false); setMessage(""); }, 2000);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      {/* Floating trigger */}
      <button
        onClick={() => setOpen(!open)}
        className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] right-3 z-40 flex h-11 w-11 items-center justify-center gap-1.5 rounded-full bg-blue-600 text-sm font-medium text-white shadow-lg hover:bg-blue-700 transition-colors sm:bottom-[4.5rem] sm:right-5 sm:h-auto sm:w-[7.5rem] sm:px-3 sm:py-2"
        aria-label="Feedback geben"
      >
        <MessageSquare size={14} />
        <span className="hidden sm:inline">Feedback</span>
      </button>

      {/* Panel */}
      {open && (
        <div className="fixed bottom-[calc(7rem+env(safe-area-inset-bottom))] right-3 z-50 w-[calc(100vw-1.5rem)] max-w-80 rounded-2xl border border-gray-200 bg-white shadow-2xl overflow-hidden sm:bottom-24 sm:right-5">
          <div className="bg-blue-600 px-4 py-3 flex items-center justify-between">
            <span className="text-sm font-semibold text-white">Feedback geben</span>
            <button onClick={() => setOpen(false)} className="text-blue-200 hover:text-white transition-colors">
              <X size={16} />
            </button>
          </div>

          {sent ? (
            <div className="p-6 text-center">
              <div className="flex justify-center mb-3">
                <div className="rounded-full bg-blue-100 p-3">
                  <Check size={20} className="text-blue-600" />
                </div>
              </div>
              <p className="font-medium text-gray-900">Danke für dein Feedback!</p>
              <p className="text-sm text-gray-500 mt-1">Wir melden uns bald.</p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="p-4 space-y-3">
              <div className="flex gap-1.5 flex-wrap">
                {CATEGORIES.map((c) => {
                  const Icon = c.icon;
                  return (
                    <button
                      key={c.value}
                      type="button"
                      onClick={() => setCategory(c.value)}
                      className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                        category === c.value
                          ? "bg-blue-600 text-white border-blue-600"
                          : "border-gray-200 text-gray-600 hover:border-gray-300"
                      }`}
                    >
                      <Icon size={11} />
                      {c.label}
                    </button>
                  );
                })}
              </div>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Was möchtest du uns mitteilen?"
                rows={4}
                minLength={5}
                required
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                type="submit"
                disabled={sending || message.length < 5}
                className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {sending ? "Wird gesendet…" : "Senden"}
              </button>
            </form>
          )}
        </div>
      )}
    </>
  );
}
