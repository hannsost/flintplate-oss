"use client";

import { useState } from "react";
import { auth } from "@/lib/auth";
import { exportApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { FileText, FileType, Link2, Globe, Check } from "lucide-react";

type Format = "pdf" | "docx" | "linkedin" | "link";

interface State {
  loading: Format | null;
  linkedinText: string | null;
  profileLink: string | null;
  copied: boolean;
}

export function ExportButtons() {
  const [shareConsent, setShareConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [state, setState] = useState<State>({
    loading: null,
    linkedinText: null,
    profileLink: null,
    copied: false,
  });

  async function downloadBlob(format: "pdf" | "docx") {
    const token = auth.getAccess();
    if (!token) return;
    setState((s) => ({ ...s, loading: format }));
    try {
      const res = format === "pdf" ? await exportApi.pdf(token) : await exportApi.docx(token);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        alert(body.detail ?? `Export fehlgeschlagen (${res.status})`);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = format === "pdf" ? "flintplate_cv.pdf" : "flintplate_cv.docx";
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setState((s) => ({ ...s, loading: null }));
    }
  }

  async function handleLinkedIn() {
    const token = auth.getAccess();
    if (!token) return;
    setState((s) => ({ ...s, loading: "linkedin" }));
    try {
      const data = await exportApi.linkedin(token);
      setState((s) => ({ ...s, linkedinText: data.text, loading: null }));
    } finally {
      setState((s) => ({ ...s, loading: null }));
    }
  }

  async function handleLink() {
    const token = auth.getAccess();
    if (!token || !shareConsent) return;
    setError(null);
    setNotice(null);
    setState((s) => ({ ...s, loading: "link" }));
    try {
      const data = await exportApi.link(token);
      setState((s) => ({ ...s, profileLink: data.url, loading: null }));
      await navigator.clipboard.writeText(data.url).then(
        () => setState((s) => ({ ...s, copied: true })),
        () => setNotice("Profil freigegeben. Du kannst den angezeigten Link manuell kopieren."),
      );
      setTimeout(() => setState((s) => ({ ...s, copied: false })), 2000);
    } catch {
      setError("Der Profil-Link konnte nicht erstellt werden. Bitte erneut versuchen.");
    } finally {
      setState((s) => ({ ...s, loading: null }));
    }
  }

  async function revokeLink() {
    const token = auth.getAccess();
    if (!token) return;
    setError(null);
    setState((s) => ({ ...s, loading: "link" }));
    try {
      await exportApi.revokeLink(token);
      setState((s) => ({ ...s, profileLink: null, copied: false }));
      setShareConsent(false);
      setNotice("Öffentlicher Profil-Link deaktiviert.");
    } catch {
      setError("Der Profil-Link konnte nicht deaktiviert werden. Bitte erneut versuchen.");
    } finally {
      setState((s) => ({ ...s, loading: null }));
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-gray-700">CV exportieren</p>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!!state.loading}
          onClick={() => downloadBlob("pdf")}
        >
          {state.loading === "pdf" ? "…" : <><FileText size={13} className="inline mr-1" />PDF</>}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!!state.loading}
          onClick={() => downloadBlob("docx")}
        >
          {state.loading === "docx" ? "…" : <><FileType size={13} className="inline mr-1" />DOCX</>}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!!state.loading}
          onClick={handleLinkedIn}
        >
          {state.loading === "linkedin" ? "…" : <><Link2 size={13} className="inline mr-1" />LinkedIn-Text</>}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!!state.loading || !shareConsent}
          onClick={handleLink}
        >
          {state.loading === "link" ? "…" : state.copied ? <><Check size={13} className="inline mr-1" />Kopiert!</> : <><Globe size={13} className="inline mr-1" />Profil öffentlich teilen</>}
        </Button>
        <Button variant="outline" size="sm" disabled={!!state.loading} onClick={revokeLink}>
          Profil-Link deaktivieren
        </Button>
      </div>
      <label className="flex items-start gap-2 text-sm text-gray-600">
        <input type="checkbox" checked={shareConsent} onChange={(e) => setShareConsent(e.target.checked)} className="mt-1" />
        Ich möchte mein Profil inklusive Kontaktangaben über einen öffentlichen Link teilen. Jeder mit diesem Link kann es aufrufen.
      </label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {notice && <p role="status" className="text-sm text-gray-700">{notice}</p>}

      {state.linkedinText && (
        <div className="relative">
          <textarea
            readOnly
            value={state.linkedinText}
            className="w-full rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700 font-mono resize-none h-40"
          />
          <button
            onClick={() => navigator.clipboard.writeText(state.linkedinText!)}
            className="absolute top-2 right-2 text-xs text-blue-600 hover:underline bg-white px-1"
          >
            Kopieren
          </button>
        </div>
      )}

      {state.profileLink && (
        <p className="text-xs text-gray-500">
          Link: <a href={state.profileLink} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">{state.profileLink}</a>
        </p>
      )}

      <p className="text-xs text-gray-500">Du kannst die Freigabe jederzeit über „Profil-Link deaktivieren“ zurücknehmen.</p>
    </div>
  );
}
