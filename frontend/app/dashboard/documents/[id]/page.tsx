"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import {
  dmsApi,
  DocumentDetail,
  DocumentRead,
  DocShareRead,
  DocActivityRead,
  DocCommentRead,
  DocCategoryRead,
} from "@/lib/api";
import { FileText, Image, Paperclip, Download, Share2, Check } from "lucide-react";

// ── helpers ────────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
function resolveFileUrl(url: string | null | undefined): string {
  if (!url) return "#";
  if (url.startsWith("/static/")) return API_BASE + url;
  return url;
}

function fmtBytes(n: number): string {
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" });
}

function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
}

function ExpiryBadge({ iso }: { iso: string }) {
  const d = daysUntil(iso);
  if (d < 0) return <span className="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700 font-medium">Abgelaufen ({Math.abs(d)}d)</span>;
  if (d <= 30) return <span className="px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-700 font-medium">Läuft in {d}d ab</span>;
  return <span className="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700 font-medium">Gültig noch {d} Tage</span>;
}

const ACTION_LABELS: Record<string, string> = {
  uploaded: "Hochgeladen",
  viewed: "Angesehen",
  edited: "Bearbeitet",
  archived: "Archiviert",
  restored: "Wiederhergestellt",
  deleted: "Gelöscht",
  shared: "Geteilt",
  share_revoked: "Freigabe widerrufen",
  commented: "Kommentar",
  new_version: "Neue Version",
};

// ── share modal ────────────────────────────────────────────────────────────

function ShareModal({ token, docId, onClose, onCreated }: {
  token: string;
  docId: string;
  onClose: () => void;
  onCreated: (s: DocShareRead) => void;
}) {
  const [email, setEmail] = useState("");
  const [accessType, setAccessType] = useState("view");
  const [expiresIn, setExpiresIn] = useState("7");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleCreate() {
    setLoading(true);
    setError("");
    try {
      const expiresAt = expiresIn
        ? new Date(Date.now() + parseInt(expiresIn) * 86400000).toISOString()
        : undefined;
      const share = await dmsApi.createShare(token, docId, {
        shared_with_email: email || undefined,
        access_type: accessType,
        expires_at: expiresAt,
        password: password || undefined,
      });
      onCreated(share);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-gray-900 mb-4">Link teilen</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">E-Mail (optional)</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="empfaenger@beispiel.de"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Zugriff</label>
            <select value={accessType} onChange={(e) => setAccessType(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="view">Nur ansehen</option>
              <option value="download">Herunterladen</option>
              <option value="sign">Unterschreiben</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Ablauf (Tage)</label>
            <input type="number" value={expiresIn} onChange={(e) => setExpiresIn(e.target.value)} min="1" max="365"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Passwort (optional)</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Kein Passwort"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        {error && <p className="text-xs text-red-600 mt-3">{error}</p>}
        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50">Abbrechen</button>
          <button onClick={handleCreate} disabled={loading}
            className="flex-1 rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {loading ? "…" : "Link erstellen"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── main ───────────────────────────────────────────────────────────────────

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const docId = params.id as string;

  const [token, setToken] = useState("");
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [categories, setCategories] = useState<DocCategoryRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"info" | "shares" | "versions" | "activity" | "comments">("info");
  const [showShareModal, setShowShareModal] = useState(false);

  // edit state
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editCategoryId, setEditCategoryId] = useState("");
  const [editExpiresAt, setEditExpiresAt] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  // comments
  const [newComment, setNewComment] = useState("");
  const [commentSaving, setCommentSaving] = useState(false);

  // share link clipboard
  const [copiedToken, setCopiedToken] = useState("");

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) return;
    setToken(t);
    Promise.all([dmsApi.get(t, docId), dmsApi.listCategories(t)]).then(([d, cats]) => {
      setDoc(d);
      setCategories(cats);
      setEditName(d.name);
      setEditDesc(d.description ?? "");
      setEditCategoryId(d.category_id ?? "");
      setEditExpiresAt(d.expires_at ? d.expires_at.substring(0, 10) : "");
      setEditTags((d.tags ?? []).join(", "));
    }).catch(() => {}).finally(() => setLoading(false));
  }, [docId]);

  async function handleSave() {
    if (!doc) return;
    setEditSaving(true);
    try {
      const updated = await dmsApi.update(token, docId, {
        name: editName,
        description: editDesc || undefined,
        category_id: editCategoryId || undefined,
        expires_at: editExpiresAt ? new Date(editExpiresAt).toISOString() : undefined,
        tags: editTags ? editTags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      });
      setDoc((prev) => prev ? { ...prev, ...updated } : prev);
    } catch { /* ignore */ }
    finally { setEditSaving(false); }
  }

  async function handleArchive() {
    if (!doc) return;
    if (!confirm("Dokument archivieren?")) return;
    const updated = await dmsApi.archive(token, docId);
    setDoc((prev) => prev ? { ...prev, ...updated } : prev);
  }

  async function handleRestore() {
    if (!doc) return;
    const updated = await dmsApi.restore(token, docId);
    setDoc((prev) => prev ? { ...prev, ...updated } : prev);
  }

  async function handleDelete() {
    if (!confirm("Dokument endgültig löschen?")) return;
    await dmsApi.delete(token, docId);
    router.push("/dashboard/documents");
  }

  async function handleRevokeShare(shareId: string) {
    await dmsApi.revokeShare(token, docId, shareId);
    setDoc((prev) => prev ? { ...prev, shares: prev.shares.filter((s) => s.id !== shareId) } : prev);
  }

  async function handleAddComment() {
    if (!newComment.trim()) return;
    setCommentSaving(true);
    try {
      const comment = await dmsApi.addComment(token, docId, newComment);
      setDoc((prev) => prev ? { ...prev, comments: [...prev.comments, comment] } : prev);
      setNewComment("");
    } catch { /* ignore */ }
    finally { setCommentSaving(false); }
  }

  async function handleDeleteComment(commentId: string) {
    await dmsApi.deleteComment(token, docId, commentId);
    setDoc((prev) => prev ? { ...prev, comments: prev.comments.filter((c) => c.id !== commentId) } : prev);
  }

  function copyShareLink(shareToken: string) {
    const url = `${window.location.origin}/public/documents/${shareToken}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopiedToken(shareToken);
      setTimeout(() => setCopiedToken(""), 2000);
    });
  }

  if (loading) return <div className="text-center py-20 text-gray-400 text-sm">Lädt…</div>;
  if (!doc) return <div className="text-center py-20 text-gray-400 text-sm">Nicht gefunden</div>;

  const TABS = [
    { id: "info", label: "Info" },
    { id: "shares", label: `Links (${doc.shares.length})` },
    { id: "versions", label: `Versionen (${doc.versions.length})` },
    { id: "activity", label: `Verlauf (${doc.activity.length})` },
    { id: "comments", label: `Kommentare (${doc.comments.length})` },
  ] as const;

  return (
    <>

    <div className="mx-auto max-w-4xl px-4 py-8">
      {showShareModal && (
        <ShareModal
          token={token}
          docId={docId}
          onClose={() => setShowShareModal(false)}
          onCreated={(s) => {
            setDoc((prev) => prev ? { ...prev, shares: [s, ...prev.shares] } : prev);
            setShowShareModal(false);
            setTab("shares");
          }}
        />
      )}

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500 mb-6">
        <Link href="/dashboard/documents" className="hover:text-blue-600">Dokumente</Link>
        <span>/</span>
        <span className="text-gray-900 font-medium">{doc.name}</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-gray-100">
            {doc.mime_type === "application/pdf" ? <FileText size={32} className="text-red-400" /> : doc.mime_type.startsWith("image/") ? <Image size={32} className="text-blue-400" /> : <Paperclip size={32} className="text-gray-400" />}
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">{doc.name}</h1>
            <p className="text-sm text-gray-400">{doc.original_filename} · {fmtBytes(doc.file_size)}</p>
            {doc.expires_at && <div className="mt-1"><ExpiryBadge iso={doc.expires_at} /></div>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <a href={resolveFileUrl(doc.file_url)} target="_blank" rel="noreferrer"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm hover:bg-gray-50 transition-colors">
            <Download size={14} className="inline mr-1" />Download
          </a>
          <button onClick={() => setShowShareModal(true)}
            className="rounded-lg border border-blue-300 px-3 py-2 text-sm text-blue-600 hover:bg-blue-50 transition-colors">
            <Share2 size={14} className="inline mr-1" />Teilen
          </button>
          {doc.status === "active" ? (
            <button onClick={handleArchive} className="rounded-lg border border-gray-300 px-3 py-2 text-sm hover:bg-gray-50">
              Archivieren
            </button>
          ) : (
            <button onClick={handleRestore} className="rounded-lg border border-green-300 px-3 py-2 text-sm text-green-600 hover:bg-green-50">
              Wiederherstellen
            </button>
          )}
          <button onClick={handleDelete} className="rounded-lg border border-red-300 px-3 py-2 text-sm text-red-600 hover:bg-red-50">
            Löschen
          </button>
        </div>
      </div>

      {/* Thumbnail */}
      {doc.thumbnail_url && (
        <div className="mb-6 rounded-xl overflow-hidden border border-gray-200 w-40">
          <img src={doc.thumbnail_url} alt="Vorschau" className="w-full" />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 mb-6">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t.id ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab: Info */}
      {tab === "info" && (
        <div className="space-y-5">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Name</label>
            <input value={editName} onChange={(e) => setEditName(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Beschreibung</label>
            <textarea value={editDesc} onChange={(e) => setEditDesc(e.target.value)} rows={3}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Kategorie</label>
              <select value={editCategoryId} onChange={(e) => setEditCategoryId(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">Keine</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.icon} {c.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Ablaufdatum</label>
              <input type="date" value={editExpiresAt} onChange={(e) => setEditExpiresAt(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Tags (kommasepariert)</label>
            <input value={editTags} onChange={(e) => setEditTags(e.target.value)} placeholder="zeugnis, 2025, chef"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <button onClick={handleSave} disabled={editSaving}
            className="rounded-lg bg-blue-600 text-white px-5 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors">
            {editSaving ? "Speichern…" : "Speichern"}
          </button>

          {/* Metadata grid */}
          <div className="mt-4 rounded-xl border border-gray-200 divide-y divide-gray-100 text-sm">
            {[
              ["MIME-Typ", doc.mime_type],
              ["Größe", fmtBytes(doc.file_size)],
              ["Hochgeladen", fmtDate(doc.created_at)],
              ["Geändert", fmtDate(doc.updated_at)],
              ["Version", `v${doc.version_number}`],
              ["OCR-Status", doc.processing_status],
              ["Sichtbarkeit", doc.visibility],
              doc.linked_entity_type ? ["Verknüpft mit", `${doc.linked_entity_type} ${doc.linked_entity_id}`] : null,
            ].filter(Boolean).map((row) => { const [k, v] = row as string[]; return (
              <div key={k} className="flex px-4 py-2.5">
                <span className="text-gray-500 w-40 shrink-0">{k}</span>
                <span className="text-gray-900 font-medium">{v}</span>
              </div>
            ); })}
          </div>

          {/* OCR preview */}
          {doc.ocr_text && (
            <div className="rounded-xl border border-gray-200 p-4">
              <p className="text-xs font-medium text-gray-700 mb-2">OCR-Text (Volltext-Vorschau)</p>
              <pre className="text-xs text-gray-500 whitespace-pre-wrap max-h-48 overflow-auto">{doc.ocr_text.substring(0, 2000)}{doc.ocr_text.length > 2000 ? "…" : ""}</pre>
            </div>
          )}
        </div>
      )}

      {/* Tab: Shares */}
      {tab === "shares" && (
        <div>
          <div className="flex justify-end mb-4">
            <button onClick={() => setShowShareModal(true)}
              className="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700">
              + Neuer Link
            </button>
          </div>
          {doc.shares.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">Keine aktiven Links.</p>
          ) : (
            <div className="space-y-3">
              {doc.shares.map((s) => (
                <div key={s.id} className="rounded-xl border border-gray-200 p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-900">
                        {s.shared_with_email ?? "Öffentlicher Link"}
                        <span className="ml-2 px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">{s.access_type}</span>
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {s.accessed_count}× aufgerufen
                        {s.expires_at && ` · Läuft ab ${new Date(s.expires_at).toLocaleDateString("de-DE")}`}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => copyShareLink(s.share_token)}
                        className="text-xs text-blue-600 hover:underline">
                        {copiedToken === s.share_token ? <><Check size={11} className="inline" /> Kopiert</> : "Link kopieren"}
                      </button>
                      <button onClick={() => handleRevokeShare(s.id)} className="text-xs text-red-600 hover:underline">
                        Widerrufen
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab: Versions */}
      {tab === "versions" && (
        <div className="space-y-2">
          {doc.versions.map((v) => (
            <div key={v.id} className={`flex items-center justify-between rounded-xl border p-4 ${v.id === docId ? "border-blue-300 bg-blue-50" : "border-gray-200"}`}>
              <div>
                <p className="text-sm font-medium text-gray-900">
                  v{v.version_number}
                  {v.is_latest_version && <span className="ml-2 px-2 py-0.5 rounded-full text-xs bg-blue-100 text-blue-700">Aktuell</span>}
                </p>
                <p className="text-xs text-gray-400">{v.original_filename} · {fmtDate(v.created_at)}</p>
              </div>
              <div className="flex gap-2">
                <a href={resolveFileUrl(v.file_url)} target="_blank" rel="noreferrer" className="text-xs text-blue-600 hover:underline">
                  Download
                </a>
                {v.id !== docId && (
                  <Link href={`/dashboard/documents/${v.id}`} className="text-xs text-gray-600 hover:underline">
                    Öffnen
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Tab: Activity */}
      {tab === "activity" && (
        <div className="space-y-2">
          {doc.activity.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">Kein Verlauf.</p>
          ) : (
            doc.activity.map((a) => (
              <div key={a.id} className="flex items-start gap-3 py-2 border-b border-gray-100 last:border-0">
                <div className="w-2 h-2 rounded-full bg-gray-400 mt-2 shrink-0" />
                <div>
                  <p className="text-sm text-gray-900">{ACTION_LABELS[a.action] ?? a.action}</p>
                  <p className="text-xs text-gray-400">{fmtDate(a.created_at)}</p>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Tab: Comments */}
      {tab === "comments" && (
        <div>
          <div className="space-y-4 mb-6">
            {doc.comments.length === 0 && (
              <p className="text-sm text-gray-400 text-center py-6">Noch keine Kommentare.</p>
            )}
            {doc.comments.map((c) => (
              <div key={c.id} className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-xs font-medium text-gray-600 shrink-0">
                  U
                </div>
                <div className="flex-1">
                  <p className="text-xs text-gray-400 mb-1">{fmtDate(c.created_at)}</p>
                  <p className="text-sm text-gray-900 bg-gray-50 rounded-xl px-3 py-2">{c.content}</p>
                </div>
                <button onClick={() => handleDeleteComment(c.id)} className="text-xs text-gray-400 hover:text-red-600 self-start mt-6">×</button>
              </div>
            ))}
          </div>
          <div className="flex gap-3">
            <input
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleAddComment()}
              placeholder="Kommentar schreiben…"
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button onClick={handleAddComment} disabled={commentSaving || !newComment.trim()}
              className="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors">
              {commentSaving ? "…" : "Senden"}
            </button>
          </div>
        </div>
      )}
    </div>
    </>
  );
}
