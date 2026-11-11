"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useStoredBoolean } from "@/lib/useStoredBoolean";
import { Menu, X } from "lucide-react";

interface PortalFrameProps {
  children: ReactNode;
  storageKey: string;
  sidebar: (collapsed: boolean, onToggle: (next: boolean) => void) => ReactNode;
}

/** Shared desktop sidebar and keyboard-accessible mobile navigation. */
export function PortalFrame({ children, storageKey, sidebar }: PortalFrameProps) {
  const [collapsed, setCollapsed] = useStoredBoolean(storageKey);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const pathname = usePathname();

  useEffect(() => {
    dialog.current?.close();
  }, [pathname]);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 768px)");
    const closeOnDesktop = () => { if (desktop.matches) dialog.current?.close(); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

  function toggle(next: boolean) {
    setCollapsed(next);
  }

  return (
    <div className="flex flex-col md:flex-row">
      <div className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] shrink-0 self-start md:block [&_aside]:static [&_aside]:h-full">{sidebar(collapsed, toggle)}</div>
      <div className="sticky top-14 z-30 border-b border-gray-200 bg-white px-4 md:hidden">
        <button type="button" onClick={() => dialog.current?.showModal()}
          className="flex min-h-11 items-center gap-2 text-sm font-medium text-gray-700"
          aria-haspopup="dialog">
          <Menu size={20} aria-hidden="true" /> Menü öffnen
        </button>
      </div>
      <dialog ref={dialog} aria-labelledby={titleId}
        onClick={(event) => { if (event.target === event.currentTarget) dialog.current?.close(); }}
        className="fixed inset-y-0 left-0 m-0 h-dvh max-h-none w-72 max-w-[85vw] border-0 p-0 backdrop:bg-slate-950/40">
        <div className="flex h-full flex-col bg-white">
          <div className="flex h-14 shrink-0 items-center justify-between border-b px-4">
            <h2 id={titleId} className="font-semibold">Navigation</h2>
            <button type="button" onClick={() => dialog.current?.close()} aria-label="Menü schließen"
              className="flex min-h-11 min-w-11 items-center justify-center rounded-lg hover:bg-gray-100">
              <X size={20} aria-hidden="true" />
            </button>
          </div>
          <div className="min-h-0 flex-1 [&_aside]:static [&_aside]:h-full [&_aside]:w-full [&_aside]:border-0 [&_aside>button]:hidden"
            onClick={(event) => { if ((event.target as Element).closest("a")) dialog.current?.close(); }}>
            {sidebar(false, toggle)}
          </div>
        </div>
      </dialog>
      <main id="main-content" className="min-w-0 flex-1">
        <div className="pb-28">{children}</div>
      </main>
    </div>
  );
}
