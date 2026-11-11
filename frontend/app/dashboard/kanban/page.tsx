"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { pipelineApi, type KanbanBoardRead, type KanbanCard, type KanbanBoardColumn } from "@/lib/api";
import { ModuleUpgradeHint } from "@/components/ui/ModuleGate";
import { fetchModules, MODULE_KEYS } from "@/lib/modules";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Card ──────────────────────────────────────────────────────────────────────
function KanbanCardItem({
  card,
  onDragStart,
}: {
  card: KanbanCard;
  onDragStart: (card: KanbanCard) => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  const mins = Math.max(0, Math.round(
    (now - new Date(card.entered_at).getTime()) / 60000
  ));
  const age =
    mins < 60
      ? `${mins}m`
      : mins < 1440
      ? `${Math.round(mins / 60)}h`
      : `${Math.round(mins / 1440)}d`;

  return (
    <div
      draggable
      onDragStart={() => onDragStart(card)}
      className="cursor-grab active:cursor-grabbing bg-white rounded-lg border border-gray-200 p-3 shadow-sm hover:shadow-md transition-shadow select-none"
    >
      <p className="text-sm font-semibold text-gray-900 truncate">
        {card.candidate_name ?? card.candidate_email}
      </p>
      <p className="text-xs text-gray-500 truncate mt-0.5">{card.job_title}</p>
      <p className="text-[10px] text-gray-400 mt-0.5">{card.company}</p>
      <p className="text-[10px] text-gray-300 mt-1 text-right">{age}</p>
    </div>
  );
}

// ── Column ─────────────────────────────────────────────────────────────────────
function KanbanColumnItem({
  col,
  onDragStart,
  onDrop,
}: {
  col: KanbanBoardColumn;
  onDragStart: (card: KanbanCard) => void;
  onDrop: (stageId: string) => void;
}) {
  const [over, setOver] = useState(false);

  return (
    <div
      className={`flex flex-col min-w-[220px] max-w-[260px] rounded-xl border bg-gray-50 transition-colors ${
        over ? "border-blue-400 bg-blue-50" : "border-gray-200"
      }`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={() => { setOver(false); onDrop(col.stage_id); }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-gray-200">
        <div className="flex items-center gap-2">
          {col.stage_color && (
            <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${col.stage_color}`} />
          )}
          <span className="text-xs font-semibold text-gray-700 truncate">{col.stage_name}</span>
        </div>
        <span className="text-xs bg-gray-200 text-gray-600 rounded-full px-1.5 py-0.5 font-medium">
          {col.cards.length}
        </span>
      </div>

      {/* Cards */}
      <div className="flex flex-col gap-2 p-2 min-h-[120px] flex-1 overflow-y-auto">
        {col.cards.map((card) => (
          <KanbanCardItem
            key={card.application_id}
            card={card}
            onDragStart={onDragStart}
          />
        ))}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function KanbanPage() {
  const router = useRouter();
  const [modules, setModules] = useState<string[] | null>(null);
  const [templates, setTemplates] = useState<{ id: string; name: string }[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  const [board, setBoard] = useState<KanbanBoardRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragCard, setDragCard] = useState<KanbanCard | null>(null);
  const [moving, setMoving] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const tokenRef = useRef<string>("");

  // Auth + module gate
  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    tokenRef.current = token;
    fetchModules(token).then(setModules).catch(() => setModules([]));
    pipelineApi.listTemplates(token).then((ts) => {
      setTemplates(ts.map((t) => ({ id: t.id, name: t.name })));
      if (ts.length > 0) setSelectedTemplate(ts[0].id);
    }).catch(() => {});
  }, [router]);

  // Load board when template changes
  const loadBoard = useCallback(async () => {
    if (!selectedTemplate) return;
    const token = auth.getAccess();
    if (!token) return;
    setLoading(true);
    try {
      const b = await pipelineApi.getKanban(token, selectedTemplate);
      setBoard(b);
    } catch {
      // template may have no assignments yet – show empty board
    } finally {
      setLoading(false);
    }
  }, [selectedTemplate]);

  useEffect(() => { loadBoard(); }, [loadBoard]);

  // WebSocket: subscribe to pipeline_move events
  useEffect(() => {
    const token = tokenRef.current;
    if (!token) return;
    const ws = new WebSocket(`${API_BASE.replace(/^http/, "ws")}/ws?token=${token}`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        if (event.type === "pipeline_move") {
          // Optimistically re-fetch the board
          loadBoard();
        }
      } catch {}
    };

    ws.onopen = () => ws.send("ping");

    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 30_000);

    return () => {
      clearInterval(ping);
      ws.close();
    };
  }, [loadBoard]);

  async function handleDrop(toStageId: string) {
    if (!dragCard || moving) return;
    const fromCol = board?.columns.find((c) =>
      c.cards.some((card) => card.application_id === dragCard.application_id)
    );
    if (fromCol?.stage_id === toStageId) return;

    const token = auth.getAccess();
    if (!token) return;

    // Optimistic update
    setBoard((prev) => {
      if (!prev) return prev;
      const cols = prev.columns.map((col) => ({
        ...col,
        cards:
          col.stage_id === toStageId
            ? [...col.cards, { ...dragCard, entered_at: new Date().toISOString() }]
            : col.cards.filter((c) => c.application_id !== dragCard.application_id),
      }));
      return { ...prev, columns: cols };
    });

    setMoving(true);
    try {
      await pipelineApi.transition(token, {
        application_id: dragCard.application_id,
        to_stage_id: toStageId,
      });
    } catch {
      // Revert on failure
      loadBoard();
    } finally {
      setMoving(false);
      setDragCard(null);
    }
  }

  if (modules !== null && !modules.includes(MODULE_KEYS.KANBAN_PIPELINE)) {
    return (
      <>

        <ModuleUpgradeHint name="Kanban Board" category="core" />
      </>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">


      <div className="px-4 py-6 max-w-full overflow-x-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5 max-w-7xl mx-auto">
          <h1 className="text-xl font-bold text-gray-900">Kanban Board</h1>
          <div className="flex items-center gap-3">
            {templates.length > 1 && (
              <select
                value={selectedTemplate}
                onChange={(e) => setSelectedTemplate(e.target.value)}
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 bg-white"
              >
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            )}
            {moving && (
              <span className="text-xs text-blue-600 animate-pulse">Wird verschoben…</span>
            )}
          </div>
        </div>

        {/* Board */}
        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          </div>
        ) : board ? (
          <div className="flex gap-4 pb-6">
            {board.columns.map((col) => (
              <KanbanColumnItem
                key={col.stage_id}
                col={col}
                onDragStart={setDragCard}
                onDrop={handleDrop}
              />
            ))}
            {board.columns.length === 0 && (
              <div className="flex-1 flex items-center justify-center py-20 text-gray-400 text-sm">
                Keine Stages konfiguriert. Erstelle zuerst eine Pipeline unter{" "}
                <a href="/dashboard/pipeline" className="text-blue-600 hover:underline ml-1">
                  Pipeline Builder
                </a>.
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-center py-20 text-gray-400 text-sm">
            Kein Template ausgewählt.
          </div>
        )}
      </div>
    </div>
  );
}
