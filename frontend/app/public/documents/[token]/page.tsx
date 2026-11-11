"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { publicApi, PublicDocumentRead } from "@/lib/api";
import { Lock, Ban, Paperclip } from "lucide-react";

function fmtBytes(n: number): string {
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function PublicDocumentPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const token = params.token as string;

  const [doc, setDoc] = useState<PublicDocumentRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [password, setPassword] = useState("");
  const [pwLoading, setPwLoading] = useState(false);

  async function fetchDoc(pw?: string) {
    setLoading(true);
    setError("");
    try {
      const url = `/public/documents/${token}${pw ? `?password=${encodeURIComponent(pw)}` : ""}`;
      const resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}${url}`);
      if (resp.status === 401) {
        setNeedsPassword(true);
        return;
      }
      if (resp.status === 410) {
        setError("Dieser Link ist abgelaufen.");
        return;
      }
      if (resp.status === 403) {
        setError("Falsches Passwort.");
        return;
      }
      if (!resp.ok) {
        setError("Link ungültig oder nicht gefunden.");
        return;
      }
      const data: PublicDocumentRead = await resp.json();
      setDoc(data);
      setNeedsPassword(false);
    } finally {
      setLoading(false);
      setPwLoading(false);
    }
  }

  useEffect(() => {
    fetchDoc();
  }, [token]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-400 text-sm">Wird geladen…</p>
      </div>
    );
  }

  if (needsPassword) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
        <div className="bg-white rounded-2xl shadow-md w-full max-w-sm p-8 text-center">
          <div className="flex justify-center mb-3"><Lock size={36} className="text-gray-400" /></div>
          <h2 className="text-lg font-bold text-gray-900 mb-1">Passwort erforderlich</h2>
          <p className="text-sm text-gray-500 mb-6">Dieses Dokument ist mit einem Passwort geschützt.</p>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { setPwLoading(true); fetchDoc(password); } }}
            placeholder="Passwort eingeben…"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {error && <p className="text-xs text-red-600 mb-3">{error}</p>}
          <button
            onClick={() => { setPwLoading(true); fetchDoc(password); }}
            disabled={pwLoading || !password}
            className="w-full rounded-lg bg-blue-600 text-white py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {pwLoading ? "…" : "Bestätigen"}
          </button>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
        <div className="bg-white rounded-2xl shadow-md w-full max-w-sm p-8 text-center">
          <div className="flex justify-center mb-3"><Ban size={36} className="text-red-400" /></div>
          <h2 className="text-lg font-bold text-gray-900 mb-2">Link nicht verfügbar</h2>
          <p className="text-sm text-gray-500">{error}</p>
        </div>
      </div>
    );
  }

  if (!doc) return null;

  const isImage = doc.mime_type.startsWith("image/");
  const isPdf = doc.mime_type === "application/pdf";

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="mx-auto max-w-3xl flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-gray-900">{doc.name}</h1>
            <p className="text-xs text-gray-400 mt-0.5">{doc.original_filename} · {fmtBytes(doc.file_size)}</p>
          </div>
          {doc.access_type !== "view" && (
            <a
              href={doc.file_url}
              download={doc.original_filename}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              ⬇ Herunterladen
            </a>
          )}
        </div>
      </div>

      {/* Preview */}
      <div className="mx-auto max-w-3xl p-6">
        {doc.description && (
          <p className="text-sm text-gray-600 mb-6 rounded-xl bg-white border border-gray-200 px-4 py-3">
            {doc.description}
          </p>
        )}

        {isImage ? (
          <div className="rounded-xl overflow-hidden border border-gray-200 bg-white">
            <img src={doc.file_url} alt={doc.name} className="w-full" />
          </div>
        ) : isPdf ? (
          <div className="rounded-xl overflow-hidden border border-gray-200 bg-white" style={{ height: "80vh" }}>
            <iframe src={doc.file_url} className="w-full h-full" title={doc.name} />
          </div>
        ) : (
          <div className="rounded-xl border border-gray-200 bg-white p-12 text-center">
            {doc.thumbnail_url ? (
              <img src={doc.thumbnail_url} alt="Vorschau" className="mx-auto max-h-64 object-contain mb-6" />
            ) : (
              <div className="flex justify-center mb-6"><Paperclip size={48} className="text-gray-300" /></div>
            )}
            <p className="text-sm text-gray-500 mb-4">Für diesen Dateityp ist keine Vorschau verfügbar.</p>
            {doc.access_type !== "view" && (
              <a
                href={doc.file_url}
                download={doc.original_filename}
                target="_blank"
                rel="noreferrer"
                className="inline-block rounded-lg bg-blue-600 text-white px-5 py-2.5 text-sm font-medium hover:bg-blue-700 transition-colors"
              >
                Datei herunterladen
              </a>
            )}
          </div>
        )}

        <p className="text-center text-xs text-gray-400 mt-6">
          Bereitgestellt über FlintPlate DMS
        </p>
      </div>
    </div>
  );
}
