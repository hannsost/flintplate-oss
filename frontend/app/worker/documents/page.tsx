"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  FileText, Download, Search, Calendar, FileImage,
  FileSpreadsheet, File, Tag,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { workerDocsApi, WorkerDocRead } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
function resolveFileUrl(url: string | null | undefined): string {
  if (!url) return "#";
  if (url.startsWith("/static/")) return API_BASE + url;
  return url;
}

function FileIcon({ mime }: { mime: string }) {
  if (mime.startsWith("image/")) return <FileImage className="w-5 h-5 text-purple-500" />;
  if (mime.includes("pdf")) return <FileText className="w-5 h-5 text-red-500" />;
  if (mime.includes("spreadsheet") || mime.includes("excel") || mime.includes("csv"))
    return <FileSpreadsheet className="w-5 h-5 text-green-500" />;
  return <File className="w-5 h-5 text-gray-400" />;
}

function isExpiringSoon(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  const diff = new Date(expiresAt).getTime() - Date.now();
  return diff > 0 && diff < 30 * 24 * 60 * 60 * 1000;
}

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  return new Date(expiresAt).getTime() < Date.now();
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function WorkerDocumentsPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [docs, setDocs] = useState<WorkerDocRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const list = await workerDocsApi.list(t);
      setDocs(list);
    } catch { setDocs([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token); }, [token, load]);

  // Unique categories from loaded docs
  const categories = Array.from(
    new Map(
      docs
        .filter((d) => d.category)
        .map((d) => [d.category!.id, d.category!])
    ).values()
  ).sort((a, b) => a.sort_order - b.sort_order);

  const filtered = docs.filter((d) => {
    if (categoryFilter && d.category_id !== categoryFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!d.name.toLowerCase().includes(q) && !d.description?.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="mb-5">
          <h1 className="text-xl font-semibold text-gray-900">Meine Dokumente</h1>
          <p className="text-sm text-gray-500 mt-0.5">Verträge, Lohnzettel und weitere Unterlagen</p>
        </div>

        {/* Filters */}
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3 mb-5">
          <div className="relative flex-1 min-w-[160px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Dokument suchen..."
              className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {categories.length > 0 && (
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Alle Kategorien</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.icon} {c.name}</option>
              ))}
            </select>
          )}
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Lade...</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
            <FileText className="w-8 h-8 text-gray-200" />
            <p className="text-sm">Keine Dokumente vorhanden</p>
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map((doc) => {
              const expired = isExpired(doc.expires_at);
              const expiring = isExpiringSoon(doc.expires_at);

              return (
                <div
                  key={doc.id}
                  className={`bg-white border rounded-xl p-4 flex items-start gap-4 ${
                    expired ? "border-red-200 bg-red-50/30" : "border-gray-200"
                  }`}
                >
                  <div className="flex-shrink-0 mt-0.5">
                    <FileIcon mime={doc.mime_type} />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{doc.name}</p>
                        {doc.description && (
                          <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{doc.description}</p>
                        )}
                      </div>
                      <a
                        href={resolveFileUrl(doc.file_url)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex-shrink-0 p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50"
                        title="Herunterladen"
                      >
                        <Download className="w-4 h-4" />
                      </a>
                    </div>

                    <div className="flex items-center flex-wrap gap-2 mt-2">
                      {doc.category && (
                        <span
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                          style={{ backgroundColor: doc.category.color + "20", color: doc.category.color }}
                        >
                          {doc.category.icon} {doc.category.name}
                        </span>
                      )}

                      {doc.tags && doc.tags.length > 0 && doc.tags.map((tag) => (
                        <span key={tag} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs text-gray-500 bg-gray-100">
                          <Tag className="w-2.5 h-2.5" />{tag}
                        </span>
                      ))}

                      <span className="text-xs text-gray-400">{fmtSize(doc.file_size)}</span>

                      <span className="text-xs text-gray-400 flex items-center gap-1">
                        <Calendar className="w-3 h-3" />
                        {fmtDate(doc.created_at)}
                      </span>

                      {expired && (
                        <span className="text-xs font-medium text-red-600">Abgelaufen</span>
                      )}
                      {expiring && !expired && (
                        <span className="text-xs font-medium text-amber-600">
                          Läuft ab {fmtDate(doc.expires_at!)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
