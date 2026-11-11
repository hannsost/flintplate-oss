"use client";

import { useEffect, useRef, useCallback } from "react";

interface Props {
  events: unknown[];
  controlEnabled: boolean;
  onMouseEvent: (
    action: "move" | "click" | "dblclick" | "scroll" | "mousedown" | "mouseup",
    nx: number,
    ny: number,
    extra?: { deltaX?: number; deltaY?: number },
  ) => void;
  onKeyEvent: (key: string, code: string, action: "keydown" | "keyup") => void;
}

type LiveReplayer = {
  startLive: (baselineTime?: number) => void;
  addEvent: (e: unknown) => void;
  destroy?: () => void;
};

export default function RRWebReplayer({ events, controlEnabled, onMouseEvent, onKeyEvent }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // mountRef = rrweb root; scaleRef = the div we apply our transform to
  const mountRef = useRef<HTMLDivElement>(null);
  const scaleRef = useRef<HTMLDivElement>(null);
  const replayerRef = useRef<LiveReplayer | null>(null);
  const prevLengthRef = useRef(0);
  const creatingRef = useRef(false);
  const eventsRef = useRef<unknown[]>(events);
  eventsRef.current = events;
  const lastMoveRef = useRef(0);

  // ── Scale ─────────────────────────────────────────────────────────────────
  const applyScale = useCallback(() => {
    const container = containerRef.current;
    const mount = mountRef.current;
    const scaleDiv = scaleRef.current;
    if (!container || !mount || !scaleDiv) return;

    const iframe = mount.querySelector("iframe") as HTMLIFrameElement | null;
    if (!iframe) return;

    // rrweb may use attributes or inline style for iframe dimensions
    const w =
      parseInt(iframe.getAttribute("width") || "0") ||
      parseInt(iframe.style.width || "0") ||
      iframe.offsetWidth ||
      0;
    const h =
      parseInt(iframe.getAttribute("height") || "0") ||
      parseInt(iframe.style.height || "0") ||
      iframe.offsetHeight ||
      0;
    if (!w || !h) return;

    const scale = Math.min(container.clientWidth / w, container.clientHeight / h);

    // Normalize rrweb's internal wrapper (iframe's parent) – remove any
    // transform or centering rrweb applied so our outer zoom is the only scaling.
    const wrapper = iframe.parentElement as HTMLElement | null;
    if (wrapper && wrapper !== mount) {
      wrapper.style.setProperty("position", "absolute", "important");
      wrapper.style.setProperty("top", "0", "important");
      wrapper.style.setProperty("left", "0", "important");
      wrapper.style.setProperty("transform", "none", "important");
      wrapper.style.setProperty("width", `${w}px`, "important");
      wrapper.style.setProperty("height", `${h}px`, "important");
    }

    // The mouse-tail canvas is a block-level sibling of the wrapper – it takes
    // layout space and pushes the iframe down. Pin it absolutely so it overlays
    // the iframe instead.
    mount.querySelectorAll<HTMLElement>("canvas.replayer-mouse-tail").forEach((c) => {
      c.style.setProperty("position", "absolute", "important");
      c.style.setProperty("top", "0", "important");
      c.style.setProperty("left", "0", "important");
    });

    // Use CSS `zoom` instead of `transform: scale`.
    // zoom is layout-aware: it scales the box AND its children while keeping
    // the element anchored at its top-left corner (no transform-origin issues).
    // rrweb cannot fight zoom via its own transform because they operate at
    // different levels of the rendering pipeline.
    scaleDiv.style.setProperty("position", "absolute", "important");
    scaleDiv.style.setProperty("top", "0", "important");
    scaleDiv.style.setProperty("left", "0", "important");
    scaleDiv.style.setProperty("width", `${w}px`, "important");
    scaleDiv.style.setProperty("height", `${h}px`, "important");
    scaleDiv.style.setProperty("zoom", `${scale}`, "important");
    scaleDiv.style.removeProperty("transform");
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      replayerRef.current?.destroy?.();
      replayerRef.current = null;
      prevLengthRef.current = 0;
      creatingRef.current = false;
    };
  }, []);

  // Reapply scale when container resizes (e.g. fullscreen toggle)
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(applyScale);
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [applyScale]);

  useEffect(() => {
    if (!containerRef.current || !mountRef.current || events.length === 0) return;

    const isNewSnapshot = !replayerRef.current || events.length <= prevLengthRef.current;

    if (isNewSnapshot) {
      if (creatingRef.current) return;
      creatingRef.current = true;

      import("rrweb").then(({ Replayer }) => {
        creatingRef.current = false;
        if (!mountRef.current) return;

        replayerRef.current?.destroy?.();

        const ReplayerClass = Replayer as unknown as new (
          events: unknown[],
          options: unknown,
        ) => LiveReplayer;

        const r = new ReplayerClass([], {
          root: mountRef.current,
          skipInactive: false,
          showWarning: false,
          showDebug: false,
          liveMode: true,
          mouseTail: false,
        });

        r.startLive();
        replayerRef.current = r;

        const allEvents = eventsRef.current;
        for (const ev of allEvents) {
          r.addEvent(ev);
        }
        prevLengthRef.current = allEvents.length;

        // Two rAFs: first lets rrweb build the iframe, second lets browser lay it out
        requestAnimationFrame(() => requestAnimationFrame(applyScale));
      }).catch(() => { creatingRef.current = false; });

    } else if (events.length > prevLengthRef.current) {
      const newEvents = events.slice(prevLengthRef.current);
      for (const ev of newEvents) {
        replayerRef.current?.addEvent(ev);
      }
      prevLengthRef.current = events.length;
      requestAnimationFrame(applyScale);
    }
  }, [events, applyScale]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Remote control overlay ────────────────────────────────────────────────
  // Normalise using scaleRef bounds (= actual rendered client-screen area).
  // Returns null when the pointer is outside the client viewport (dark area).
  function toNormalised(e: React.MouseEvent<HTMLDivElement>): { nx: number; ny: number } | null {
    const el = scaleRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const nx = (e.clientX - rect.left) / rect.width;
    const ny = (e.clientY - rect.top) / rect.height;
    if (nx < 0 || nx > 1 || ny < 0 || ny > 1) return null;
    return { nx, ny };
  }

  // Cursor shows crosshair only over the client-screen area
  function overlayStyle(e: React.MouseEvent<HTMLDivElement>): void {
    if (!containerRef.current) return;
    containerRef.current.style.cursor =
      controlEnabled && toNormalised(e) ? "crosshair" : "default";
  }

  return (
    <div
      ref={containerRef}
      className="w-full h-full overflow-hidden bg-gray-900 relative"
      style={{ cursor: "default" }}
      onMouseMove={(e) => {
        overlayStyle(e);
        if (!controlEnabled) return;
        const pos = toNormalised(e);
        if (!pos) return;
        // Throttle to ~60 fps to reduce WS traffic and lag
        const now = Date.now();
        if (now - lastMoveRef.current < 16) return;
        lastMoveRef.current = now;
        onMouseEvent("move", pos.nx, pos.ny);
      }}
      onMouseDown={(e) => {
        if (!controlEnabled) return;
        const pos = toNormalised(e);
        if (!pos) return;
        onMouseEvent("mousedown", pos.nx, pos.ny);
      }}
      onMouseUp={(e) => {
        if (!controlEnabled) return;
        const pos = toNormalised(e);
        if (!pos) return;
        onMouseEvent("mouseup", pos.nx, pos.ny);
      }}
      onClick={(e) => {
        if (!controlEnabled) return;
        const pos = toNormalised(e);
        if (!pos) return;
        onMouseEvent("click", pos.nx, pos.ny);
      }}
      onDoubleClick={(e) => {
        if (!controlEnabled) return;
        const pos = toNormalised(e);
        if (!pos) return;
        onMouseEvent("dblclick", pos.nx, pos.ny);
      }}
      onWheel={(e) => {
        if (!controlEnabled) return;
        const pos = toNormalised(e);
        if (!pos) return;
        onMouseEvent("scroll", pos.nx, pos.ny, { deltaX: e.deltaX, deltaY: e.deltaY });
      }}
      onKeyDown={(e) => {
        if (!controlEnabled) return;
        onKeyEvent(e.key, e.code, "keydown");
      }}
      onKeyUp={(e) => {
        if (!controlEnabled) return;
        onKeyEvent(e.key, e.code, "keyup");
      }}
      tabIndex={controlEnabled ? 0 : -1}
    >
      {/*
        scaleRef: we apply our CSS transform here (rrweb can't interfere)
        mountRef: passed to rrweb as root – rrweb renders inside here
      */}
      <div ref={scaleRef} style={{ position: "absolute", top: 0, left: 0 }}>
        <div ref={mountRef} />
      </div>
    </div>
  );
}
