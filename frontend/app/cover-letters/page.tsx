"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { coverLetterApi, ApiError, type CoverLetterRead } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { CoverLetterModal } from "@/components/ai/CoverLetterModal";
import { Button } from "@/components/ui/button";
import { ModuleGate, ModuleUpgradeHint } from "@/components/ui/ModuleGate";
import { fetchModules, MODULE_KEYS } from "@/lib/modules";

function LetterCard({
  letter,
  onDelete,
  onView,
}: {
  letter: CoverLetterRead;
  onDelete: (id: string) => void;
  onView: (letter: CoverLetterRead) => void;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-gray-900 truncate">{letter.position}</p>
          <p className="text-sm text-gray-500 mt-0.5 truncate">{letter.company}</p>
          <p className="text-xs text-gray-400 mt-1">
            {new Date(letter.created_at).toLocaleDateString("de-DE", {
              day: "2-digit", month: "2-digit", year: "numeric",
            })}
            {" · "}
            <span className="font-mono">{letter.model_used}</span>
            {" · "}
            {letter.tone}
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button variant="outline" size="sm" onClick={() => onView(letter)}>
            Ansehen
          </Button>
          <button
            onClick={() => onDelete(letter.id)}
            className="text-xs text-red-400 hover:text-red-600 px-1"
          >
            ✕
          </button>
        </div>
      </div>
      <p className="mt-3 text-xs text-gray-500 line-clamp-3 whitespace-pre-line">
        {letter.generated_text.slice(0, 200)}…
      </p>
      {letter.ai_generated && (
        <span className="mt-2 inline-block rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-xs text-amber-700">
          KI-generiert
        </span>
      )}
    </div>
  );
}

function LetterViewModal({
  letter,
  onClose,
}: {
  letter: CoverLetterRead;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(letter.generated_text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div>
            <h2 className="font-semibold text-gray-900">{letter.position}</h2>
            <p className="text-sm text-gray-500">{letter.company}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="p-5 overflow-y-auto max-h-[70vh] space-y-4">
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            ⚠️ KI-generiert · {letter.model_used} · bitte vor Versand prüfen
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-800 whitespace-pre-line leading-relaxed font-mono">
            {letter.generated_text}
          </div>
          <div className="flex justify-end gap-2">
            <Button onClick={handleCopy}>{copied ? "✓ Kopiert!" : "Kopieren"}</Button>
            <Button variant="outline" onClick={onClose}>Schließen</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function CoverLettersPage() {
  const router = useRouter();
  const [letters, setLetters] = useState<CoverLetterRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [viewing, setViewing] = useState<CoverLetterRead | null>(null);
  const [modules, setModules] = useState<string[]>([]);

  const fetchLetters = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    setLoading(true);
    try {
      const [data, mods] = await Promise.all([
        coverLetterApi.list(token),
        fetchModules(token),
      ]);
      setLetters(data);
      setModules(mods);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run once on mount only

  useEffect(() => { fetchLetters(); }, [fetchLetters]);

  async function handleDelete(id: string) {
    if (!confirm("Anschreiben löschen?")) return;
    const token = auth.getAccess();
    if (!token) return;
    try {
      await coverLetterApi.delete(token, id);
      setLetters((prev) => prev.filter((l) => l.id !== id));
    } catch {
      // ignore
    }
  }

  function handleGenerated(letter: CoverLetterRead) {
    setLetters((prev) => [letter, ...prev]);
    setShowCreate(false);
  }

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-3xl px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Meine Anschreiben</h1>
            <p className="text-sm text-gray-400 mt-0.5">{letters.length} gespeichert</p>
          </div>
          <ModuleGate modules={modules} moduleKey={MODULE_KEYS.AI_COVER_LETTER} fallback={
            <span className="text-xs text-gray-400 bg-gray-100 px-3 py-1.5 rounded-lg">🔒 KI nicht verfügbar</span>
          }>
            <Button onClick={() => setShowCreate(true)} size="sm">
              ✨ Neu generieren
            </Button>
          </ModuleGate>
        </div>

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : letters.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <p className="text-4xl mb-3">✉️</p>
            <p className="font-medium">Noch keine Anschreiben</p>
            <p className="text-sm mt-1">Klicke auf &quot;Neu generieren&quot; oder nutze den Bewerben-Button in der Jobliste.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {letters.map((letter) => (
              <LetterCard
                key={letter.id}
                letter={letter}
                onDelete={handleDelete}
                onView={setViewing}
              />
            ))}
          </div>
        )}
      </main>

      {showCreate && (
        <CoverLetterModal
          onClose={() => setShowCreate(false)}
          onGenerated={handleGenerated}
        />
      )}

      {viewing && (
        <LetterViewModal letter={viewing} onClose={() => setViewing(null)} />
      )}
    </>
  );
}
