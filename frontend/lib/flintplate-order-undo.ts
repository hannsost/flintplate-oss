import type { CartRow, OrderDraft } from "./flintplate-drafts";

interface DraftContent { cart: CartRow[]; note: string }
interface UndoStep { content: DraftContent; label: string; group: string | null }
export interface OrderUndo { key: string | null; revision: string | null; steps: UndoStep[] }
export const ORDER_UNDO_LIMIT = 30;
export const emptyOrderUndo = (): OrderUndo => ({ key: null, revision: null, steps: [] });
const content = (draft: OrderDraft): DraftContent => ({ cart: structuredClone(draft.cart), note: draft.note });

/** Rebase local history when only request/validation metadata was persisted. */
export function rebaseOrderUndo(history: OrderUndo, key: string, previousRevision: string | null, nextRevision: string): OrderUndo {
  return history.key === key && history.revision === previousRevision
    ? { ...history, revision: nextRevision }
    : { key, revision: nextRevision, steps: [] };
}

export function recordOrderUndo(history: OrderUndo, key: string, before: OrderDraft, after: OrderDraft, label: string, group: string | null = null): OrderUndo {
  const next = rebaseOrderUndo(history, key, before.revision, after.revision);
  const previous = content(before);
  if (JSON.stringify(previous) === JSON.stringify(content(after))) return next;
  // Continuous typing in one focused note field is one editable action.
  if (group && next.steps.at(-1)?.group === group) return next;
  return { ...next, steps: [...next.steps, { content: previous, label, group }].slice(-ORDER_UNDO_LIMIT) };
}

/** Undo is valid only for this exact local AND persisted draft revision.
 * No saved key, pending command, uncertainty or target can be resurrected. */
export function orderUndoContent(history: OrderUndo, key: string, current: OrderDraft, storedRevision: string | null): DraftContent | null {
  if (current.uncertain || history.key !== key || history.revision !== current.revision || storedRevision !== current.revision) return null;
  const previous = history.steps.at(-1);
  return previous ? structuredClone(previous.content) : null;
}

export function commitOrderUndo(history: OrderUndo, key: string, previousRevision: string, nextRevision: string): OrderUndo {
  const next = rebaseOrderUndo(history, key, previousRevision, nextRevision);
  return { ...next, steps: next.steps.slice(0, -1) };
}
