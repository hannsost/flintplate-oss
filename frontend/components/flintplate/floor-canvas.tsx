"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { ArrowUpRight, Move, Radio, Square, Waves } from "lucide-react";
import { labels, type Resource } from "@/lib/flintplate";
import { FLOOR_GRID_BACKGROUND, FLOOR_GRID_STEP, floorCoordinates, floorPixels, pointerFloorPosition, type FloorDimensions, type FloorPoint } from "@/lib/flintplate-floor-geometry";
import { Empty } from "./shared";

export interface FloorResourceView { resource: Resource; state: string; note: string }
interface Props {
  label: string; resources: FloorResourceView[]; compact?: boolean; editing: boolean; snap: boolean;
  disabled: boolean; selectedId?: string; pendingId?: string;
  onSelect: (resource: Resource) => void;
  onMove: (resource: Resource, position: FloorPoint) => Promise<void>;
}
interface Gesture {
  pointer: number; resource: Resource; start: FloorPoint; grab: FloorPoint;
  itemWidth: number; itemHeight: number; moved: boolean; position: FloorPoint; outside: boolean;
}

/** Real DOM dimensions, pointer capture and a visible destination shared by mouse and touch. */
export function FloorCanvas({ label, resources, compact, editing, snap, disabled, selectedId, pendingId, onSelect, onMove }: Props) {
  const canvas = useRef<HTMLDivElement>(null), gesture = useRef<Gesture | null>(null);
  const [size, setSize] = useState({ width: compact ? 480 : 540, height: compact ? 355 : 470 });
  const [preview, setPreview] = useState<Gesture | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const suppressClick = useRef({ id: "", until: 0 });
  const dimensions = (resource: Resource): FloorDimensions => ({ ...size, itemWidth: resource.kind === "table" ? 100 : 132, itemHeight: resource.kind === "table" ? 77 : 85 });

  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const update = () => setSize({ width: node.clientWidth, height: node.clientHeight });
    update(); const observer = new ResizeObserver(update); observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const cancel = (event: globalThis.KeyboardEvent) => { if (event.key === "Escape" && gesture.current) { suppressClick.current = { id: gesture.current.resource.id, until: Date.now() + 600 }; gesture.current = null; setPreview(null); setAnnouncement("Verschieben verworfen. Die Position bleibt unverändert."); } };
    window.addEventListener("keydown", cancel);
    return () => window.removeEventListener("keydown", cancel);
  }, []);

  function pointerDown(event: PointerEvent<HTMLButtonElement>, resource: Resource) {
    // A fresh pointer sequence is a deliberate interaction, including an
    // immediate tap after dragging. Only the drag's own generated click is suppressed.
    if (event.isPrimary) suppressClick.current = { id: "", until: 0 };
    if (!editing || disabled || !event.isPrimary || event.button !== 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    gesture.current = { pointer: event.pointerId, resource, start: { x: event.clientX, y: event.clientY }, grab: { x: event.clientX - rect.left, y: event.clientY - rect.top }, itemWidth: rect.width, itemHeight: rect.height, moved: false, position: { x: resource.x, y: resource.y }, outside: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function locate(event: PointerEvent<HTMLButtonElement>, active: Gesture) {
    const rect = canvas.current!.getBoundingClientRect();
    const scaleX = canvas.current!.clientWidth / rect.width, scaleY = canvas.current!.clientHeight / rect.height;
    const position = pointerFloorPosition({ x: (event.clientX - rect.left) * scaleX, y: (event.clientY - rect.top) * scaleY }, { x: 0, y: 0 }, { x: active.grab.x * scaleX, y: active.grab.y * scaleY }, { width: canvas.current!.clientWidth, height: canvas.current!.clientHeight, itemWidth: active.itemWidth * scaleX, itemHeight: active.itemHeight * scaleY }, snap);
    return { ...active, position, outside: event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom };
  }
  function pointerMove(event: PointerEvent<HTMLButtonElement>) {
    const active = gesture.current;
    if (!active || active.pointer !== event.pointerId || !canvas.current) return;
    if (!active.moved && Math.hypot(event.clientX - active.start.x, event.clientY - active.start.y) < (event.pointerType === "touch" ? 9 : 5)) return;
    event.preventDefault();
    const next = locate(event, { ...active, moved: true });
    gesture.current = next; setPreview(next);
  }
  function cancelPointer(event: PointerEvent<HTMLButtonElement>) {
    if (gesture.current?.pointer !== event.pointerId) return;
    suppressClick.current = { id: gesture.current.resource.id, until: Date.now() + 600 }; gesture.current = null; setPreview(null); setAnnouncement("Verschieben abgebrochen. Die Position bleibt unverändert.");
  }
  function pointerUp(event: PointerEvent<HTMLButtonElement>) {
    const active = gesture.current;
    if (!active || active.pointer !== event.pointerId) return;
    gesture.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (!active.moved || !canvas.current) return;
    event.preventDefault(); suppressClick.current = { id: active.resource.id, until: Date.now() + 600 };
    const next = locate(event, active); setPreview(null);
    if (next.outside) { setAnnouncement("Außerhalb des Raums losgelassen. Die Position bleibt unverändert."); return; }
    if (next.position.x === active.resource.x && next.position.y === active.resource.y) return;
    setAnnouncement(`${active.resource.name}: Zielposition übernommen. Wird gespeichert.`);
    void onMove(active.resource, next.position);
  }
  function keyMove(event: KeyboardEvent<HTMLButtonElement>, resource: Resource) {
    if (!editing || disabled || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const current = floorPixels(resource, dimensions(resource)), amount = event.shiftKey ? FLOOR_GRID_STEP * 2 : snap ? FLOOR_GRID_STEP : 4;
    const next = floorCoordinates({ x: current.x + (event.key === "ArrowLeft" ? -amount : event.key === "ArrowRight" ? amount : 0), y: current.y + (event.key === "ArrowUp" ? -amount : event.key === "ArrowDown" ? amount : 0) }, dimensions(resource), snap);
    if (next.x !== resource.x || next.y !== resource.y) void onMove(resource, next);
  }

  return <div className="fp-floor-board"><div className="fp-floor-scroll"><div ref={canvas} style={FLOOR_GRID_BACKGROUND} className={`fp-floorplan ${compact ? "compact" : ""} ${editing ? "is-editing" : ""} ${snap ? "with-snap" : ""}`} role="group" aria-label={`Grundriss ${label}`}>
    <span className="fp-plan-room-label">{label}</span>
    {resources.map(({ resource, state, note }) => {
      const active = preview?.resource.id === resource.id ? preview : null;
      const position = floorPixels(active?.position ?? resource, dimensions(resource));
      const origin = active ? floorPixels(resource, dimensions(resource)) : null;
      return <div key={resource.id}>
        {origin && <span className={`fp-floor-origin ${resource.kind !== "table" ? "activity" : ""}`} aria-hidden="true" style={{ left: origin.x, top: origin.y }} />}
        <button type="button" className={`fp-resource ${resource.kind !== "table" ? "activity" : ""} ${state} ${selectedId === resource.id ? "selected" : ""} ${active ? "is-dragging" : ""} ${active?.outside ? "is-outside" : ""} ${pendingId === resource.id ? "is-saving" : ""}`} style={{ left: position.x, top: position.y, touchAction: editing ? "none" : "auto" }} aria-label={`${resource.name}, ${labels[resource.kind]}, ${note}${editing ? ", zum Verschieben ziehen oder Pfeiltasten nutzen" : ""}`} aria-busy={pendingId === resource.id || undefined} onPointerDown={event => pointerDown(event, resource)} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelPointer} onLostPointerCapture={cancelPointer} onKeyDown={event => keyMove(event, resource)} onClick={event => { if (event.detail > 0 && suppressClick.current.id === resource.id && suppressClick.current.until > Date.now()) return; onSelect(resource); }}>
          <span className="fp-chair top" /><span className="fp-chair bottom" />{resource.kind === "pedal_boat" ? <Waves size={23} /> : resource.kind === "table" ? <Square size={21} /> : <Radio size={22} />}<strong>{resource.name}</strong><small>{resource.seats} {resource.kind === "table" ? "Plätze" : "Personen"}</small><small className="fp-resource-state">{pendingId === resource.id ? "Wird gespeichert …" : note}</small>
          {active && <span className="fp-floor-drop-hint"><Move size={14} />{active.outside ? "Loslassen verwirft" : "Hier ablegen"}</span>}
        </button>
      </div>;
    })}
    {!resources.length && <Empty title="Hier entsteht dein Grundriss">Lege Räume und Ressourcen an.</Empty>}
    <span className="fp-entrance">EINGANG / ZUGANG <ArrowUpRight size={14} /></span>
  </div></div><p className="fp-visually-hidden" role="status" aria-live="polite">{announcement}</p></div>;
}
