"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { authApi, pipelineApi } from "@/lib/api";
import type { PipelineTemplateRead, PipelineStageRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// ── Color options ─────────────────────────────────────────────────────────────
const COLORS = [
  { label: "Grau",    value: "bg-gray-100",    dot: "bg-gray-400" },
  { label: "Blau",    value: "bg-blue-100",    dot: "bg-blue-500" },
  { label: "Gelb",    value: "bg-yellow-100",  dot: "bg-yellow-500" },
  { label: "Grün",    value: "bg-blue-100", dot: "bg-blue-500" },
  { label: "Lila",    value: "bg-purple-100",  dot: "bg-purple-500" },
  { label: "Rot",     value: "bg-red-100",     dot: "bg-red-500" },
  { label: "Orange",  value: "bg-orange-100",  dot: "bg-orange-500" },
];

function dotColor(colorClass: string | null): string {
  return COLORS.find((c) => c.value === colorClass)?.dot ?? "bg-gray-300";
}

// ── Stage config drawer ───────────────────────────────────────────────────────
function StageConfigDrawer({
  stage,
  onSave,
  onDelete,
  onClose,
}: {
  stage: PipelineStageRead;
  onSave: (data: Partial<PipelineStageRead>) => Promise<void>;
  onDelete: () => Promise<void>;
  onClose: () => void;
}) {
  const [name, setName] = useState(stage.name);
  const [color, setColor] = useState(stage.color ?? "bg-gray-100");
  const [isTerminal, setIsTerminal] = useState(stage.is_terminal);
  const [slaHours, setSlaHours] = useState<string>(stage.sla_hours?.toString() ?? "");
  const [requiresApproval, setRequiresApproval] = useState(stage.requires_approval);
  const [approverRole, setApproverRole] = useState(stage.approver_role ?? "recruiter");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave({
        name,
        color,
        is_terminal: isTerminal,
        sla_hours: slaHours ? parseInt(slaHours) : null,
        requires_approval: requiresApproval,
        approver_role: requiresApproval ? approverRole : null,
      });
      onClose();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Stage "${stage.name}" wirklich löschen?`)) return;
    setDeleting(true);
    try {
      await onDelete();
      onClose();
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/30">
      <div className="h-full w-full max-w-sm bg-white shadow-xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h3 className="font-semibold text-gray-900">Stage konfigurieren</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded border border-gray-200 px-3 py-2 text-sm"
            />
          </div>

          {/* Color */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-2">Farbe</label>
            <div className="flex flex-wrap gap-2">
              {COLORS.map((c) => (
                <button
                  key={c.value}
                  onClick={() => setColor(c.value)}
                  className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
                    color === c.value ? "border-blue-500 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-600"
                  }`}
                >
                  <span className={`w-2.5 h-2.5 rounded-full ${c.dot}`} />
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          {/* Terminal */}
          <div className="flex items-center gap-3">
            <input
              id="terminal"
              type="checkbox"
              checked={isTerminal}
              onChange={(e) => setIsTerminal(e.target.checked)}
              className="rounded"
            />
            <label htmlFor="terminal" className="text-sm text-gray-700">Terminal-Stage (End-Zustand)</label>
          </div>

          {/* SLA */}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">SLA (Stunden bis Eskalation)</label>
            <input
              type="number"
              min={1}
              value={slaHours}
              onChange={(e) => setSlaHours(e.target.value)}
              placeholder="z.B. 48"
              className="w-full rounded border border-gray-200 px-3 py-2 text-sm"
            />
            <p className="text-[10px] text-gray-400 mt-1">Leer lassen = kein SLA</p>
          </div>

          {/* Approval */}
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <input
                id="approval"
                type="checkbox"
                checked={requiresApproval}
                onChange={(e) => setRequiresApproval(e.target.checked)}
                className="rounded"
              />
              <label htmlFor="approval" className="text-sm text-gray-700">Freigabe erforderlich</label>
            </div>
            {requiresApproval && (
              <select
                value={approverRole}
                onChange={(e) => setApproverRole(e.target.value)}
                className="w-full rounded border border-gray-200 px-3 py-2 text-sm"
              >
                <option value="recruiter">Recruiter</option>
                <option value="admin">Administrator</option>
              </select>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="border-t px-5 py-4 flex items-center justify-between">
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="text-sm text-red-500 hover:text-red-700 disabled:opacity-50"
          >
            {deleting ? "Lösche…" : "Stage löschen"}
          </button>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={onClose}>Abbrechen</Button>
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving ? "Speichere…" : "Speichern"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function PipelinePage() {
  const router = useRouter();
  const [templates, setTemplates] = useState<PipelineTemplateRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedStage, setSelectedStage] = useState<PipelineStageRead | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [creatingTemplate, setCreatingTemplate] = useState(false);
  const [newTemplateName, setNewTemplateName] = useState("");

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }
    authApi.me(token).then((u) => {
      if (u.role !== "recruiter") router.push("/profile");
    }).catch(() => router.push("/login"));
  }, [router]);

  const load = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) return;
    setLoading(true);
    try {
      const t = await pipelineApi.listTemplates(token);
      setTemplates(t);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleCreateTemplate(e: React.FormEvent) {
    e.preventDefault();
    if (!newTemplateName.trim()) return;
    const token = auth.getAccess();
    if (!token) return;
    try {
      const t = await pipelineApi.createTemplate(token, { name: newTemplateName.trim() });
      setTemplates((prev) => [...prev, t]);
      setNewTemplateName("");
      setCreatingTemplate(false);
    } catch {
      alert("Erstellen fehlgeschlagen.");
    }
  }

  async function handleAddStage(templateId: string) {
    const token = auth.getAccess();
    if (!token) return;
    const template = templates.find((t) => t.id === templateId);
    if (!template) return;
    const nextPos = template.stages.length;
    try {
      await pipelineApi.addStage(token, templateId, {
        name: "Neue Stage",
        position: nextPos,
        color: "bg-gray-100",
      });
      await load();
    } catch {
      alert("Stage hinzufügen fehlgeschlagen.");
    }
  }

  async function handleSaveStage(stageId: string, data: Partial<PipelineStageRead>) {
    const token = auth.getAccess();
    if (!token) return;
    await pipelineApi.updateStage(token, stageId, data);
    await load();
  }

  async function handleDeleteStage(stageId: string) {
    const token = auth.getAccess();
    if (!token) return;
    await pipelineApi.deleteStage(token, stageId);
    await load();
  }

  if (loading) {
    return (
      <>

        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      </>
    );
  }

  return (
    <>

      <main className="mx-auto max-w-5xl px-4 py-8 space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Pipeline Builder</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Konfiguriere Bewerbungs-Stages, SLAs, Trigger und Freigaben.
            </p>
          </div>
          <Button onClick={() => setCreatingTemplate(true)}>+ Neue Pipeline</Button>
        </div>

        {/* Create template form */}
        {creatingTemplate && (
          <form onSubmit={handleCreateTemplate} className="flex items-center gap-3">
            <input
              autoFocus
              value={newTemplateName}
              onChange={(e) => setNewTemplateName(e.target.value)}
              placeholder="Pipeline-Name, z.B. Tech-Recruiting"
              className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm"
              required
            />
            <Button type="submit" size="sm">Erstellen</Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setCreatingTemplate(false)}>
              Abbrechen
            </Button>
          </form>
        )}

        {/* Templates */}
        {templates.length === 0 && !creatingTemplate && (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-gray-500">Keine Pipelines vorhanden.</p>
              <p className="text-sm text-gray-400 mt-1">Erstelle deine erste Pipeline oben.</p>
            </CardContent>
          </Card>
        )}

        {templates.map((template) => (
          <Card key={template.id}>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">
                  {template.name}
                  {template.is_default && (
                    <span className="ml-2 text-xs font-normal text-blue-600 bg-blue-50 border border-blue-200 rounded-full px-2 py-0.5">
                      Standard
                    </span>
                  )}
                  {template.recruiter_id === null && (
                    <span className="ml-2 text-xs font-normal text-gray-400 bg-gray-50 border border-gray-200 rounded-full px-2 py-0.5">
                      System
                    </span>
                  )}
                </CardTitle>
                <span className="text-xs text-gray-400">{template.stages.length} Stages</span>
              </div>
            </CardHeader>

            <CardContent>
              {/* Stage columns */}
              <div className="flex gap-2 overflow-x-auto pb-2">
                {template.stages.map((stage) => (
                  <div
                    key={stage.id}
                    className={`flex-shrink-0 w-40 rounded-lg border-2 p-3 cursor-pointer transition-all hover:shadow-sm ${
                      stage.is_terminal ? "border-gray-300 opacity-70" : "border-gray-200"
                    } ${stage.color ?? "bg-gray-50"}`}
                    onClick={() => {
                      if (template.recruiter_id !== null) {
                        setSelectedStage(stage);
                        setSelectedTemplateId(template.id);
                      }
                    }}
                  >
                    <div className="flex items-center gap-1.5 mb-2">
                      <span className={`w-2.5 h-2.5 rounded-full ${dotColor(stage.color)}`} />
                      <span className="text-xs font-medium text-gray-700 truncate">{stage.name}</span>
                    </div>
                    <p className="text-[10px] text-gray-400">#{stage.position + 1}</p>
                    {stage.sla_hours && (
                      <p className="text-[10px] text-yellow-600 mt-1">⏱ SLA {stage.sla_hours}h</p>
                    )}
                    {stage.requires_approval && (
                      <p className="text-[10px] text-purple-600 mt-0.5">✓ Freigabe</p>
                    )}
                    {stage.is_terminal && (
                      <p className="text-[10px] text-gray-400 mt-0.5">■ Terminal</p>
                    )}
                  </div>
                ))}

                {/* Add stage button (only for non-system templates) */}
                {template.recruiter_id !== null && (
                  <button
                    onClick={() => handleAddStage(template.id)}
                    className="flex-shrink-0 w-32 rounded-lg border-2 border-dashed border-gray-200 p-3 text-xs text-gray-400 hover:border-blue-300 hover:text-blue-600 transition-colors flex items-center justify-center"
                  >
                    + Stage
                  </button>
                )}
              </div>

              {template.recruiter_id === null && (
                <p className="text-xs text-gray-400 mt-3 italic">
                  System-Pipeline – kann nicht bearbeitet werden. Erstelle eine eigene Pipeline zum Anpassen.
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </main>

      {/* Stage config drawer */}
      {selectedStage && selectedTemplateId && (
        <StageConfigDrawer
          stage={selectedStage}
          onClose={() => setSelectedStage(null)}
          onSave={async (data) => {
            await handleSaveStage(selectedStage.id, data);
            setSelectedStage(null);
          }}
          onDelete={async () => {
            await handleDeleteStage(selectedStage.id);
            setSelectedStage(null);
          }}
        />
      )}
    </>
  );
}
