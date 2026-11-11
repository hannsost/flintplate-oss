"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { dmsApi, DocumentRead, DocCategoryRead, ExpiryDashboard } from "@/lib/api";
import {
  FileText, Image, FileType, BarChart2, Paperclip,
  Upload, FolderOpen, Clock, LayoutGrid, List, CalendarDays,
} from "lucide-react";

// ── helpers ────────────────────────────────────────────────────────────────

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
}

function ExpiryBadge({ iso }: { iso: string }) {
  const d = daysUntil(iso);
  if (d < 0) return <span className="px-1.5 py-0.5 rounded text-xs bg-red-100 text-red-700 font-medium">Abgelaufen</span>;
  if (d <= 30) return <span className="px-1.5 py-0.5 rounded text-xs bg-amber-100 text-amber-700 font-medium">Läuft in {d}d ab</span>;
  return <span className="px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-700 font-medium">Gültig bis {new Date(iso).toLocaleDateString("de-DE")}</span>;
}

function MimeIcon({ mime, size = 20, className = "" }: { mime: string; size?: number; className?: string }) {
  if (mime === "application/pdf") return <FileText size={size} className={className || "text-red-400"} />;
  if (mime.startsWith("image/")) return <Image size={size} className={className || "text-blue-400"} />;
  if (mime.includes("word")) return <FileType size={size} className={className || "text-blue-600"} />;
  if (mime.includes("excel") || mime.includes("sheet")) return <BarChart2 size={size} className={className || "text-green-500"} />;
  return <Paperclip size={size} className={className || "text-gray-400"} />;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-600",
  done: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

// ── upload dropzone ────────────────────────────────────────────────────────

function UploadDropzone({ token, onUploaded }: { token: string; onUploaded: (doc: DocumentRead) => void }) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setError("");
    setUploading(true);
    try {
      let fileUrl = "";
      try {
        const presign = await dmsApi.presign(token, {
          filename: file.name,
          mime_type: file.type,
          file_size: file.size,
        });
        // Direct upload to S3
        await fetch(presign.upload_url, {
          method: "PUT",
          headers: { "Content-Type": file.type },
          body: file,
        });
        fileUrl = presign.file_url;
      } catch {
        // S3 not configured — use placeholder URL
        fileUrl = `local://${file.name}`;
      }

      const doc = await dmsApi.create(token, {
        name: file.name.replace(/\.[^.]+$/, ""),
        original_filename: file.name,
        file_url: fileUrl,
        mime_type: file.type || "application/octet-stream",
        file_size: file.size,
      });
      onUploaded(doc);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload fehlgeschlagen");
    } finally {
      setUploading(false);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      onClick={() => inputRef.current?.click()}
      className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
        dragging ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-gray-400 hover:bg-gray-50"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
        accept=".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx,.xls,.xlsx,.txt"
      />
      {uploading ? (
        <p className="text-sm text-gray-500 animate-pulse">Wird hochgeladen…</p>
      ) : (
        <>
          <Upload size={28} className="text-gray-300 mb-2" />
          <p className="text-sm text-gray-600 font-medium">Datei hierher ziehen oder klicken</p>
          <p className="text-xs text-gray-400 mt-1">PDF, Bild, Word, Excel – max. 50 MB</p>
        </>
      )}
      {error && <p className="text-xs text-red-600 mt-2">{error}</p>}
    </div>
  );
}

// ── expiry widget ──────────────────────────────────────────────────────────

function ExpiryWidget({ expiry }: { expiry: ExpiryDashboard }) {
  if (expiry.overdue.length === 0 && expiry.expiring_soon.length === 0) return null;
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 mb-6">
      <h3 className="text-sm font-semibold text-amber-800 mb-3 flex items-center gap-1.5"><Clock size={14} /> Ablauf-Übersicht</h3>
      <div className="flex gap-6 text-sm">
        {expiry.overdue.length > 0 && (
          <div>
            <span className="font-medium text-red-700">{expiry.overdue.length}</span>
            <span className="text-red-600 ml-1">abgelaufen</span>
          </div>
        )}
        {expiry.expiring_soon.length > 0 && (
          <div>
            <span className="font-medium text-amber-700">{expiry.expiring_soon.length}</span>
            <span className="text-amber-600 ml-1">in 30 Tagen ablaufend</span>
          </div>
        )}
      </div>
      <div className="mt-3 space-y-1">
        {[...expiry.overdue, ...expiry.expiring_soon].slice(0, 5).map((d) => (
          <Link
            key={d.id}
            href={`/dashboard/documents/${d.id}`}
            className="flex items-center justify-between text-xs text-gray-700 hover:text-blue-600 py-0.5"
          >
            <span className="truncate max-w-xs flex items-center gap-1.5"><MimeIcon mime={d.mime_type} size={13} /> {d.name}</span>
            {d.expires_at && <ExpiryBadge iso={d.expires_at} />}
          </Link>
        ))}
      </div>
    </div>
  );
}

// ── document cards ─────────────────────────────────────────────────────────

type View = "grid" | "list" | "timeline";

function DocCard({ doc, selected, onSelect, onDelete }: {
  doc: DocumentRead;
  selected: boolean;
  onSelect: (id: string, v: boolean) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className={`relative group rounded-xl border bg-white p-4 hover:shadow-md transition-shadow ${selected ? "border-blue-400 ring-2 ring-blue-200" : "border-gray-200"}`}>
      <input
        type="checkbox"
        checked={selected}
        onChange={(e) => onSelect(doc.id, e.target.checked)}
        className="absolute top-3 left-3 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={(e) => e.stopPropagation()}
      />
      <Link href={`/dashboard/documents/${doc.id}`} className="block">
        {doc.thumbnail_url ? (
          <img src={doc.thumbnail_url} alt={doc.name} className="w-full h-28 object-cover rounded-lg mb-3 bg-gray-100" />
        ) : (
          <div className="w-full h-28 rounded-lg mb-3 bg-gray-100 flex items-center justify-center">
            <MimeIcon mime={doc.mime_type} size={40} />
          </div>
        )}
        <p className="text-sm font-medium text-gray-900 truncate">{doc.name}</p>
        <p className="text-xs text-gray-400 mt-0.5">{fmtBytes(doc.file_size)}</p>
        {doc.category && (
          <span className="inline-block mt-1.5 px-2 py-0.5 rounded-full text-xs font-medium" style={{ background: doc.category.color + "22", color: doc.category.color }}>
            {doc.category.icon} {doc.category.name}
          </span>
        )}
        {doc.expires_at && (
          <div className="mt-1.5">
            <ExpiryBadge iso={doc.expires_at} />
          </div>
        )}
      </Link>
      <div className={`mt-2 text-xs px-1.5 py-0.5 rounded inline-block ${STATUS_COLORS[doc.processing_status] ?? "bg-gray-100 text-gray-500"}`}>
        {doc.processing_status === "pending" ? "Verarbeitung…" : doc.processing_status === "done" ? "Bereit" : "Fehler"}
      </div>
    </div>
  );
}

function DocRow({ doc, selected, onSelect }: {
  doc: DocumentRead;
  selected: boolean;
  onSelect: (id: string, v: boolean) => void;
}) {
  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-4 py-3">
        <input type="checkbox" checked={selected} onChange={(e) => onSelect(doc.id, e.target.checked)} />
      </td>
      <td className="px-4 py-3">
        <Link href={`/dashboard/documents/${doc.id}`} className="flex items-center gap-2">
          <MimeIcon mime={doc.mime_type} size={18} />
          <div>
            <p className="text-sm font-medium text-gray-900 hover:text-blue-600">{doc.name}</p>
            <p className="text-xs text-gray-400">{doc.original_filename}</p>
          </div>
        </Link>
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">{doc.category ? `${doc.category.icon} ${doc.category.name}` : "—"}</td>
      <td className="px-4 py-3 text-xs text-gray-500">{fmtBytes(doc.file_size)}</td>
      <td className="px-4 py-3 text-xs">
        {doc.expires_at ? <ExpiryBadge iso={doc.expires_at} /> : <span className="text-gray-400">—</span>}
      </td>
      <td className="px-4 py-3 text-xs text-gray-400">{new Date(doc.updated_at).toLocaleDateString("de-DE")}</td>
      <td className="px-4 py-3 text-xs text-gray-500">v{doc.version_number}</td>
    </tr>
  );
}

function TimelineRow({ doc }: { doc: DocumentRead }) {
  return (
    <Link href={`/dashboard/documents/${doc.id}`} className="flex items-center gap-4 p-3 rounded-xl hover:bg-gray-50 border border-gray-100 transition-colors">
      <MimeIcon mime={doc.mime_type} size={22} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{doc.name}</p>
        <p className="text-xs text-gray-400">{doc.category ? `${doc.category.icon} ${doc.category.name}` : "Keine Kategorie"} · {fmtBytes(doc.file_size)}</p>
      </div>
      {doc.expires_at && <ExpiryBadge iso={doc.expires_at} />}
    </Link>
  );
}

// ── main page ──────────────────────────────────────────────────────────────

export default function DocumentsPage() {
  const [token, setToken] = useState("");
  const [docs, setDocs] = useState<DocumentRead[]>([]);
  const [categories, setCategories] = useState<DocCategoryRead[]>([]);
  const [expiry, setExpiry] = useState<ExpiryDashboard | null>(null);
  const [view, setView] = useState<View>("grid");
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterStatus, setFilterStatus] = useState("active");
  const [showUpload, setShowUpload] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [bulkLoading, setBulkLoading] = useState(false);
  const searchTimeout = useRef<ReturnType<typeof setTimeout>>(null);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) return;
    setToken(t);
    Promise.all([
      dmsApi.listCategories(t),
      dmsApi.expiry(t),
    ]).then(([cats, exp]) => {
      setCategories(cats);
      setExpiry(exp);
    }).catch(() => {});
  }, []);

  const loadDocs = useCallback(async (t: string, q?: string, catId?: string, st?: string) => {
    setLoading(true);
    const params: Record<string, string> = { status: st ?? filterStatus };
    if (q) params.q = q;
    if (catId) params.category_id = catId;
    try {
      const result = await dmsApi.list(t, params);
      setDocs(result);
    } catch {
      setDocs([]);
    } finally {
      setLoading(false);
    }
  }, [filterStatus]);

  useEffect(() => {
    if (!token) return;
    loadDocs(token, search, filterCategory, filterStatus);
  }, [token, filterCategory, filterStatus]);

  function handleSearchChange(v: string) {
    setSearch(v);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => {
      if (token) loadDocs(token, v, filterCategory, filterStatus);
    }, 350);
  }

  function onSelect(id: string, v: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      v ? next.add(id) : next.delete(id);
      return next;
    });
  }

  function onSelectAll() {
    if (selected.size === docs.length) setSelected(new Set());
    else setSelected(new Set(docs.map((d) => d.id)));
  }

  async function handleBulkDownload() {
    if (selected.size === 0) return;
    setBulkLoading(true);
    try {
      const resp = await dmsApi.bulkDownload(token, Array.from(selected));
      if (!resp.ok) throw new Error("Download fehlgeschlagen");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "dokumente.zip";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Bulk-Download fehlgeschlagen");
    } finally {
      setBulkLoading(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Dokument wirklich löschen?")) return;
    await dmsApi.delete(token, id).catch(() => {});
    setDocs((prev) => prev.filter((d) => d.id !== id));
    setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
  }

  // Timeline: sorted by expires_at
  const timelineDocs = [...docs].sort((a, b) => {
    if (!a.expires_at) return 1;
    if (!b.expires_at) return -1;
    return new Date(a.expires_at).getTime() - new Date(b.expires_at).getTime();
  });

  return (
    <>

    <div className="mx-auto max-w-6xl px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dokumente</h1>
          <p className="text-sm text-gray-500 mt-0.5">{docs.length} Dokument{docs.length !== 1 ? "e" : ""}</p>
        </div>
        <button
          onClick={() => setShowUpload((v) => !v)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
        >
          + Hochladen
        </button>
      </div>

      {/* Expiry widget */}
      {expiry && <ExpiryWidget expiry={expiry} />}

      {/* Upload area */}
      {showUpload && (
        <div className="mb-6">
          <UploadDropzone
            token={token}
            onUploaded={(doc) => {
              setDocs((prev) => [doc, ...prev]);
              setShowUpload(false);
            }}
          />
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <input
          type="search"
          placeholder="Suchen…"
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />

        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Alle Kategorien</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.icon} {c.name}</option>
          ))}
        </select>

        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="active">Aktiv</option>
          <option value="archived">Archiviert</option>
          <option value="deleted">Gelöscht</option>
        </select>

        <div className="ml-auto flex items-center gap-2">
          {selected.size > 0 && (
            <button
              onClick={handleBulkDownload}
              disabled={bulkLoading}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {bulkLoading ? "…" : `⬇ ${selected.size} herunterladen`}
            </button>
          )}
          {/* View toggles */}
          {(["grid", "list", "timeline"] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-2 rounded-lg text-sm border transition-colors ${view === v ? "bg-gray-900 text-white border-gray-900" : "border-gray-300 text-gray-600 hover:bg-gray-50"}`}
            >
              {v === "grid" ? <LayoutGrid size={15} /> : v === "list" ? <List size={15} /> : <CalendarDays size={15} />}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="text-center py-16 text-gray-400 text-sm">Lädt…</div>
      ) : docs.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <FolderOpen size={44} className="text-gray-300 mb-3" />
          <p className="text-sm">Keine Dokumente gefunden.</p>
          <button onClick={() => setShowUpload(true)} className="mt-3 text-sm text-blue-600 hover:underline">Erstes Dokument hochladen</button>
        </div>
      ) : view === "grid" ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {docs.map((d) => (
            <DocCard key={d.id} doc={d} selected={selected.has(d.id)} onSelect={onSelect} onDelete={handleDelete} />
          ))}
        </div>
      ) : view === "list" ? (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 w-8">
                  <input type="checkbox" onChange={onSelectAll} checked={selected.size === docs.length && docs.length > 0} />
                </th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase">Kategorie</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase">Größe</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase">Ablauf</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase">Geändert</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase">Version</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {docs.map((d) => (
                <DocRow key={d.id} doc={d} selected={selected.has(d.id)} onSelect={onSelect} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-gray-500 mb-3 font-medium">Sortiert nach Ablaufdatum</p>
          {timelineDocs.map((d) => (
            <TimelineRow key={d.id} doc={d} />
          ))}
        </div>
      )}
    </div>
    </>
  );
}
