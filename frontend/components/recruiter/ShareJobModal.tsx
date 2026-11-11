"use client";

import { useState } from "react";
import { auth } from "@/lib/auth";
import { recruiterApi } from "@/lib/api";
import type { LinkedInShareResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { X, Check } from "lucide-react";

interface Props {
  jobId: string;
  jobTitle: string;
  onClose: () => void;
}

export function ShareJobModal({ jobId, jobTitle, onClose }: Props) {
  const [result, setResult] = useState<LinkedInShareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    const token = auth.getAccess();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const r = await recruiterApi.generateJobLinkedInPost(token, jobId);
      setResult(r);
    } catch {
      setError("Post konnte nicht generiert werden.");
    } finally {
      setLoading(false);
    }
  }

  async function copyToClipboard() {
    if (!result) return;
    await navigator.clipboard.writeText(result.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-xl rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-base font-bold text-gray-900">LinkedIn-Post generieren</h2>
            <p className="text-xs text-gray-500 mt-0.5 truncate max-w-xs">{jobTitle}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
          >
            <X size={15} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {!result && !loading && (
            <div className="text-center py-4 space-y-3">
              <p className="text-sm text-gray-600">
                Generiere einen LinkedIn-Post für diese Stelle mit KI.
              </p>
              <Button onClick={generate} className="bg-[#0077b5] hover:bg-[#006097] text-white">
                LinkedIn-Post generieren
              </Button>
            </div>
          )}

          {loading && (
            <div className="flex items-center justify-center py-10 gap-2">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-[#0077b5] border-t-transparent" />
              <span className="text-sm text-gray-500">KI generiert deinen Post…</span>
            </div>
          )}

          {error && <p className="text-sm text-red-600 text-center">{error}</p>}

          {result && (
            <>
              {!result.ai_generated && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700">
                  {result.disclaimer}
                </div>
              )}

              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Dein LinkedIn-Post</p>
                  <span className="text-xs text-gray-400">{result.text.length} Zeichen</span>
                </div>
                <textarea
                  className="w-full min-h-[220px] rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-y"
                  value={result.text}
                  onChange={(e) => setResult({ ...result, text: e.target.value })}
                />
              </div>

              <div className="flex gap-2">
                <Button
                  className="flex-1 bg-[#0077b5] hover:bg-[#006097] text-white"
                  onClick={copyToClipboard}
                >
                  {copied ? <><Check size={13} className="inline" /> Kopiert!</> : "In Zwischenablage kopieren"}
                </Button>
                <Button variant="outline" onClick={generate} disabled={loading}>
                  Neu generieren
                </Button>
              </div>

              <p className="text-[11px] text-gray-400 text-center">
                Tipp: Füge den Text direkt in LinkedIn ein und passe ihn nach Bedarf an.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
