"use client";

/**
 * Remote control: receives mouse/keyboard events from the support agent
 * and simulates them in the requester's browser.
 */

export type RemoteMouseEvent = {
  type: "support.control_mouse";
  session_id: string;
  x: number;        // percentage of viewport width (0–1)
  y: number;        // percentage of viewport height (0–1)
  action: "move" | "click" | "dblclick" | "contextmenu" | "scroll" | "mousedown" | "mouseup";
  button?: number;
  deltaX?: number;
  deltaY?: number;
};

export type RemoteKeyboardEvent = {
  type: "support.control_keyboard";
  session_id: string;
  key: string;
  code: string;
  action: "keydown" | "keyup" | "keypress";
  modifiers?: string[];  // "ctrl" | "alt" | "shift" | "meta"
};

/** Convert normalised coordinates (0–1) to viewport pixels */
function toViewport(nx: number, ny: number): { x: number; y: number } {
  return {
    x: nx * window.innerWidth,
    y: ny * window.innerHeight,
  };
}

// Map action names → DOM event type strings
const ACTION_TO_DOM: Record<string, string> = {
  move:        "mousemove",
  click:       "click",
  dblclick:    "dblclick",
  contextmenu: "contextmenu",
  mousedown:   "mousedown",
  mouseup:     "mouseup",
};

export function simulateMouseEvent(event: RemoteMouseEvent): void {
  const { x: clientX, y: clientY } = toViewport(event.x, event.y);
  const target = document.elementFromPoint(clientX, clientY) as HTMLElement | null;
  if (!target) return;

  if (event.action === "scroll") {
    target.scrollBy({ left: event.deltaX ?? 0, top: event.deltaY ?? 0, behavior: "smooth" });
    moveCursor(clientX, clientY);
    return;
  }

  const init: MouseEventInit = {
    bubbles: true,
    cancelable: true,
    clientX,
    clientY,
    button: event.button ?? 0,
    view: window,
  };

  if (event.action === "click") {
    // Full click sequence so focus + selection work correctly
    target.dispatchEvent(new MouseEvent("mousedown", { ...init, buttons: 1 }));
    target.dispatchEvent(new MouseEvent("mouseup", init));
    target.dispatchEvent(new MouseEvent("click", init));
    // Focus focusable elements so subsequent keyboard events land on them
    if (typeof (target as HTMLElement).focus === "function") {
      (target as HTMLElement).focus();
    }
  } else {
    const domEvent = ACTION_TO_DOM[event.action] ?? event.action;
    const buttons = event.action === "mousedown" ? 1 : 0;
    target.dispatchEvent(new MouseEvent(domEvent, { ...init, buttons }));
  }

  moveCursor(clientX, clientY);
}

export function simulateKeyboardEvent(event: RemoteKeyboardEvent): void {
  const modifiers = event.modifiers ?? [];
  const init: KeyboardEventInit = {
    bubbles: true,
    cancelable: true,
    key: event.key,
    code: event.code,
    ctrlKey: modifiers.includes("ctrl"),
    altKey: modifiers.includes("alt"),
    shiftKey: modifiers.includes("shift"),
    metaKey: modifiers.includes("meta"),
  };

  const el = (document.activeElement as HTMLElement | null) ?? document.body;
  el.dispatchEvent(new KeyboardEvent(event.action, init));

  // For keydown on printable single characters without Ctrl/Meta: inject the
  // character into the focused input/textarea using the native value setter so
  // React's controlled-input onChange fires correctly.
  if (
    event.action === "keydown" &&
    event.key.length === 1 &&
    !init.ctrlKey && !init.metaKey &&
    (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)
  ) {
    const proto = el instanceof HTMLInputElement
      ? HTMLInputElement.prototype
      : HTMLTextAreaElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (nativeSetter) {
      nativeSetter.call(el, el.value + event.key);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  // Backspace handling for React inputs
  if (
    event.action === "keydown" &&
    event.key === "Backspace" &&
    (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)
  ) {
    const proto = el instanceof HTMLInputElement
      ? HTMLInputElement.prototype
      : HTMLTextAreaElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (nativeSetter && el.value.length > 0) {
      nativeSetter.call(el, el.value.slice(0, -1));
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
}

// ── Virtual cursor overlay ────────────────────────────────────────────────────

let _cursor: HTMLElement | null = null;
let _label: HTMLElement | null = null;

export function mountAgentCursor(agentName: string): void {
  if (_cursor) return;
  _cursor = document.createElement("div");
  _cursor.id = "support-agent-cursor";
  _cursor.style.cssText = `
    position: fixed;
    width: 20px;
    height: 20px;
    border-radius: 50% 50% 50% 0;
    background: #2563eb;
    border: 2px solid white;
    box-shadow: 0 2px 8px rgba(0,0,0,.35);
    pointer-events: none;
    z-index: 999999;
    transform: rotate(-45deg);
    transition: left .05s linear, top .05s linear;
    left: -40px; top: -40px;
  `;

  _label = document.createElement("div");
  _label.style.cssText = `
    position: absolute;
    bottom: -22px;
    left: 12px;
    background: #2563eb;
    color: white;
    font-size: 10px;
    font-family: sans-serif;
    padding: 1px 5px;
    border-radius: 4px;
    white-space: nowrap;
    pointer-events: none;
  `;
  _label.textContent = agentName;
  _cursor.appendChild(_label);
  document.body.appendChild(_cursor);
}

export function moveCursor(x: number, y: number): void {
  if (!_cursor) return;
  _cursor.style.left = `${x - 4}px`;
  _cursor.style.top = `${y - 4}px`;
}

export function unmountAgentCursor(): void {
  _cursor?.remove();
  _cursor = null;
  _label = null;
}
