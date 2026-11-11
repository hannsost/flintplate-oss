"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
  MarkerType,
  NodeToolbar,
  Position,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { auth } from "@/lib/auth";
import {
  orgChartApi,
  type OrgChartFull,
  type OrgNodeStatus,
  type OrgEdgeType,
  type OrgNodeRead,
} from "@/lib/api";

// ── Dagre auto-layout ──────────────────────────────────────────────────────────
import dagre from "@dagrejs/dagre";

function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  direction: "TB" | "LR" = "TB",
): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, ranksep: 80, nodesep: 40, marginx: 20, marginy: 20 });

  nodes.forEach((n) => {
    g.setNode(n.id, { width: n.measured?.width ?? 200, height: n.measured?.height ?? 88 });
  });
  edges.forEach((e) => {
    g.setEdge(e.source, e.target);
  });

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    const w = n.measured?.width ?? 200;
    const h = n.measured?.height ?? 88;
    return { ...n, position: { x: pos.x - w / 2, y: pos.y - h / 2 } };
  });
}

// ── Node status styling ────────────────────────────────────────────────────────
const STATUS_CONFIG: Record<OrgNodeStatus, { label: string; bg: string; border: string; badge: string; dot: string }> = {
  filled:     { label: "Besetzt",     bg: "bg-white",       border: "border-green-400",  badge: "bg-green-100 text-green-700",   dot: "#16a34a" },
  open:       { label: "Offen",       bg: "bg-amber-50",    border: "border-amber-400",  badge: "bg-amber-100 text-amber-700",   dot: "#d97706" },
  temp:       { label: "Zeitarbeit",  bg: "bg-blue-50",     border: "border-blue-400",   badge: "bg-blue-100 text-blue-700",     dot: "#2563eb" },
  contractor: { label: "Freelancer",  bg: "bg-purple-50",   border: "border-purple-400", badge: "bg-purple-100 text-purple-700", dot: "#9333ea" },
  planned:    { label: "Geplant",     bg: "bg-gray-50",     border: "border-gray-300",   badge: "bg-gray-100 text-gray-500",     dot: "#9ca3af" },
};

// ── Custom OrgNode component ────────────────────────────────────────────────────
interface OrgNodeData {
  title: string;
  department: string | null;
  person_name: string | null;
  status: OrgNodeStatus;
  color: string | null;
  onEdit: (id: string) => void;
  onAddChild: (id: string) => void;
  onDelete: (id: string) => void;
}

function OrgNodeComponent({ id, data, selected }: { id: string; data: OrgNodeData; selected: boolean }) {
  const cfg = STATUS_CONFIG[data.status];
  const deptColor = data.color ?? "#6b7280";

  return (
    <>
      <NodeToolbar isVisible={selected} position={Position.Top} offset={6}>
        <div className="flex items-center gap-1 bg-white rounded-lg shadow-lg border border-gray-200 px-2 py-1.5">
          <button
            onClick={() => data.onAddChild(id)}
            className="text-xs text-blue-600 hover:text-blue-800 px-2 py-0.5 rounded hover:bg-blue-50 transition-colors"
          >
            + Kind
          </button>
          <button
            onClick={() => data.onEdit(id)}
            className="text-xs text-gray-600 hover:text-gray-900 px-2 py-0.5 rounded hover:bg-gray-100 transition-colors"
          >
            Bearbeiten
          </button>
          <button
            onClick={() => data.onDelete(id)}
            className="text-xs text-red-500 hover:text-red-700 px-2 py-0.5 rounded hover:bg-red-50 transition-colors"
          >
            Löschen
          </button>
        </div>
      </NodeToolbar>

      <div
        className={`rounded-xl border-2 shadow-sm overflow-hidden min-w-[180px] max-w-[220px] cursor-pointer transition-shadow ${cfg.bg} ${cfg.border} ${selected ? "shadow-md ring-2 ring-blue-400 ring-offset-1" : "hover:shadow-md"}`}
      >
        {/* Department color bar */}
        <div className="h-1.5 w-full" style={{ backgroundColor: deptColor }} />

        <div className="px-3 py-2.5">
          {/* Title */}
          <p className="font-semibold text-gray-900 text-xs leading-tight mb-1 truncate">{data.title}</p>

          {/* Department */}
          {data.department && (
            <p className="text-[10px] text-gray-500 truncate mb-1.5">{data.department}</p>
          )}

          {/* Person */}
          {data.person_name ? (
            <p className="text-[11px] text-gray-700 truncate">{data.person_name}</p>
          ) : (
            <p className="text-[11px] text-gray-400 italic">Unbesetzt</p>
          )}

          {/* Status badge */}
          <div className="mt-2 flex items-center gap-1.5">
            <span className={`inline-block text-[10px] font-medium px-1.5 py-0.5 rounded-full ${cfg.badge}`}>
              {cfg.label}
            </span>
          </div>
        </div>
      </div>
    </>
  );
}

const nodeTypes = { orgNode: OrgNodeComponent };

// ── Edit Drawer ─────────────────────────────────────────────────────────────────
interface NodeFormData {
  title: string;
  department: string;
  person_name: string;
  person_email: string;
  status: OrgNodeStatus;
  color: string;
}

function EditDrawer({
  node,
  onSave,
  onClose,
}: {
  node: Node | null;
  onSave: (id: string, data: NodeFormData) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<NodeFormData>(() => {
    const d = node?.data as unknown as OrgNodeData | undefined;
    return {
      title: d?.title ?? "",
      department: d?.department ?? "",
      person_name: d?.person_name ?? "",
      person_email: "",
      status: d?.status ?? "open",
      color: d?.color ?? "#6b7280",
    };
  });

  if (!node) return null;

  return (
    <div className="absolute right-0 top-0 bottom-0 w-80 bg-white border-l border-gray-200 shadow-xl z-50 flex flex-col">
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 text-sm">Position bearbeiten</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        <Field label="Stellenbezeichnung *">
          <input
            type="text"
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            className="input-sm"
            placeholder="z.B. Head of Engineering"
          />
        </Field>

        <Field label="Abteilung">
          <input
            type="text"
            value={form.department}
            onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))}
            className="input-sm"
            placeholder="z.B. Engineering"
          />
        </Field>

        <Field label="Name der Person">
          <input
            type="text"
            value={form.person_name}
            onChange={(e) => setForm((f) => ({ ...f, person_name: e.target.value }))}
            className="input-sm"
            placeholder="Vorname Nachname"
          />
        </Field>

        <Field label="E-Mail">
          <input
            type="email"
            value={form.person_email}
            onChange={(e) => setForm((f) => ({ ...f, person_email: e.target.value }))}
            className="input-sm"
            placeholder="max@firma.de"
          />
        </Field>

        <Field label="Status">
          <select
            value={form.status}
            onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as OrgNodeStatus }))}
            className="input-sm"
          >
            {Object.entries(STATUS_CONFIG).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </Field>

        <Field label="Abteilungsfarbe">
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={form.color}
              onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
              className="h-8 w-12 rounded border border-gray-300 cursor-pointer p-0.5"
            />
            <input
              type="text"
              value={form.color}
              onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
              maxLength={7}
              className="input-sm font-mono flex-1"
              placeholder="#6b7280"
            />
          </div>
        </Field>
      </div>

      <div className="px-5 py-4 border-t border-gray-100">
        <button
          onClick={() => { if (form.title.trim()) onSave(node.id, form); }}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 rounded-lg text-sm transition-colors"
        >
          Speichern
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs font-medium text-gray-600 block mb-1.5">{label}</label>
      {children}
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────────────
function makeNode(
  id: string,
  title: string,
  position: { x: number; y: number },
  status: OrgNodeStatus,
  callbacks: { onEdit: (id: string) => void; onAddChild: (id: string) => void; onDelete: (id: string) => void },
): Node {
  return {
    id,
    type: "orgNode",
    position,
    data: { title, department: null, person_name: null, status, color: null, ...callbacks },
  };
}

function chartToFlow(
  chart: OrgChartFull,
  callbacks: { onEdit: (id: string) => void; onAddChild: (id: string) => void; onDelete: (id: string) => void },
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = chart.nodes.map((n) => ({
    id: n.id,
    type: "orgNode",
    position: { x: n.pos_x, y: n.pos_y },
    data: {
      title: n.title,
      department: n.department,
      person_name: n.person_name,
      status: n.status,
      color: n.color,
      ...callbacks,
    },
  }));

  const edges: Edge[] = chart.edges.map((e) => ({
    id: e.id,
    source: e.source_id,
    target: e.target_id,
    type: "smoothstep",
    animated: e.edge_type === "dotted",
    style: e.edge_type === "dotted" ? { strokeDasharray: "6 3" } : undefined,
    label: e.label ?? undefined,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
  }));

  return { nodes, edges };
}

// ── Main editor page ────────────────────────────────────────────────────────────
export default function OrgChartEditorPage() {
  const params = useParams();
  const router = useRouter();
  const chartId = params?.id as string;

  const [chart, setChart] = useState<OrgChartFull | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [editingNode, setEditingNode] = useState<Node | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const nodeIdCounter = useRef(100);

  // Stable callbacks
  const handleEdit = useCallback((id: string) => {
    setNodes((nds) => {
      const n = nds.find((n) => n.id === id);
      if (n) setEditingNode(n);
      return nds;
    });
  }, [setNodes]);

  const handleDelete = useCallback((id: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== id));
    setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
  }, [setNodes, setEdges]);

  const handleAddChild = useCallback((parentId: string) => {
    const newId = `new-${nodeIdCounter.current++}`;
    const parent = nodes.find((n) => n.id === parentId);
    const pos = parent
      ? { x: parent.position.x, y: parent.position.y + 140 }
      : { x: 200, y: 200 };

    const newNode = makeNode(newId, "Neue Position", pos, "open", { onEdit: handleEdit, onAddChild: handleAddChild, onDelete: handleDelete });
    setNodes((nds) => [...nds, newNode]);
    setEdges((eds) => [
      ...eds,
      {
        id: `e-${parentId}-${newId}`,
        source: parentId,
        target: newId,
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      },
    ]);
    // Immediately open edit drawer for new node
    setEditingNode(newNode);
  }, [nodes, setNodes, setEdges, handleEdit, handleDelete]);

  // Reload callbacks into existing nodes when they change (needed for closures)
  const callbacks = useMemo(
    () => ({ onEdit: handleEdit, onAddChild: handleAddChild, onDelete: handleDelete }),
    [handleEdit, handleAddChild, handleDelete],
  );

  // Load chart
  useEffect(() => {
    const token = auth.getToken();
    if (!token) { router.replace("/login"); return; }
    orgChartApi.get(token, chartId)
      .then((c) => {
        setChart(c);
        const { nodes: n, edges: e } = chartToFlow(c, callbacks);
        setNodes(n);
        setEdges(e);
      })
      .catch(() => router.replace("/dashboard/org-charts"))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartId]);

  // Keep callbacks fresh in node data
  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        data: { ...n.data, ...callbacks },
      }))
    );
  }, [callbacks, setNodes]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            type: "smoothstep",
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
          },
          eds,
        )
      );
    },
    [setEdges],
  );

  function handleAddRoot() {
    const newId = `new-${nodeIdCounter.current++}`;
    const pos = { x: 200 + nodes.length * 60, y: 60 };
    const newNode = makeNode(newId, "Neue Position", pos, "open", callbacks);
    setNodes((nds) => [...nds, newNode]);
    setEditingNode(newNode);
  }

  function handleAutoLayout() {
    const direction = chart?.chart_type === "flat" ? "LR" : "TB";
    setNodes((nds) => applyDagreLayout(nds, edges, direction));
  }

  function handleSaveNodeEdit(id: string, form: NodeFormData) {
    setNodes((nds) =>
      nds.map((n) =>
        n.id === id
          ? {
              ...n,
              data: {
                ...n.data,
                title: form.title,
                department: form.department || null,
                person_name: form.person_name || null,
                status: form.status,
                color: form.color,
              },
            }
          : n,
      )
    );
    setEditingNode(null);
  }

  async function handleSave() {
    const token = auth.getToken();
    if (!token || !chart) return;
    setSaving(true);
    setSaveError(null);
    try {
      await orgChartApi.save(token, chartId, {
        nodes: nodes.map((n) => ({
          id: n.id.startsWith("new-") ? undefined : n.id,
          title: (n.data as unknown as OrgNodeData).title,
          department: (n.data as unknown as OrgNodeData).department,
          person_name: (n.data as unknown as OrgNodeData).person_name,
          status: (n.data as unknown as OrgNodeData).status,
          color: (n.data as unknown as OrgNodeData).color,
          pos_x: n.position.x,
          pos_y: n.position.y,
          node_width: n.measured?.width ?? 200,
          node_height: n.measured?.height ?? 88,
        })),
        edges: edges.map((e) => ({
          id: e.id.startsWith("e-") ? undefined : e.id,
          source_id: e.source,
          target_id: e.target,
          edge_type: (e.animated ? "dotted" : "solid") as OrgEdgeType,
          label: typeof e.label === "string" ? e.label : null,
        })),
      });
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Speichern fehlgeschlagen");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">

        <div className="flex items-center justify-center h-96">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-screen bg-gray-50">
      {/* Top bar */}

      <div className="bg-white border-b border-gray-200 px-4 py-2.5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 text-sm">
          <Link href="/dashboard/org-charts" className="text-gray-400 hover:text-gray-600">
            ← Organigramme
          </Link>
          <span className="text-gray-300">/</span>
          <span className="font-medium text-gray-800 truncate max-w-[200px]">{chart?.name}</span>
          {chart && (
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full capitalize">
              {chart.chart_type}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleAddRoot}
            className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium px-3 py-1.5 rounded-lg transition-colors"
          >
            + Position
          </button>
          <button
            onClick={handleAutoLayout}
            className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium px-3 py-1.5 rounded-lg transition-colors"
          >
            Auto-Layout
          </button>
          {saveError && (
            <span className="text-xs text-red-500">{saveError}</span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="text-xs bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold px-4 py-1.5 rounded-lg transition-colors"
          >
            {saving ? "Speichern…" : "Speichern"}
          </button>
        </div>
      </div>

      {/* Editor canvas */}
      <div className="flex flex-1 relative" style={{ height: "calc(100vh - 112px)" }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          deleteKeyCode="Delete"
          className="bg-gray-50"
        >
          <Background color="#e5e7eb" gap={20} />
          <Controls position="bottom-left" />
          <MiniMap
            position="bottom-right"
            nodeColor={(n) => {
              const status = (n.data as unknown as OrgNodeData)?.status ?? "open";
              return STATUS_CONFIG[status as OrgNodeStatus]?.dot ?? "#9ca3af";
            }}
            style={{ borderRadius: 8, border: "1px solid #e5e7eb" }}
          />

          {/* Legend */}
          <Panel position="top-left">
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-3 text-xs space-y-1.5">
              <p className="font-semibold text-gray-700 mb-2">Legende</p>
              {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: v.dot }} />
                  <span className="text-gray-600">{v.label}</span>
                </div>
              ))}
              <p className="text-gray-400 pt-1.5 border-t border-gray-100 leading-relaxed">
                Ziehen: Node verschieben<br />
                Verbinden: Handle → Handle<br />
                Entf: Auswahl löschen
              </p>
            </div>
          </Panel>
        </ReactFlow>

        {/* Edit Drawer */}
        <EditDrawer key={editingNode?.id ?? "closed"}
          node={editingNode}
          onSave={handleSaveNodeEdit}
          onClose={() => setEditingNode(null)}
        />
      </div>

      {/* Input styles injected via global */}
      <style>{`
        .input-sm {
          width: 100%;
          border: 1px solid #d1d5db;
          border-radius: 0.5rem;
          padding: 0.375rem 0.625rem;
          font-size: 0.8125rem;
          outline: none;
          transition: box-shadow 0.15s;
        }
        .input-sm:focus {
          box-shadow: 0 0 0 2px #3b82f6;
          border-color: #3b82f6;
        }
      `}</style>
    </div>
  );
}
