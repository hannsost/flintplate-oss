"use client";

import Link from "next/link";
import { useStoredBoolean } from "@/lib/useStoredBoolean";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import {
  LayoutDashboard,
  Clock,
  CalendarDays,
  MessageSquare,
  FolderOpen,
  UtensilsCrossed,
  Wrench,
  CheckSquare,
  Receipt,
  Ticket,
  User,
  Video,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

type WorkerNavItem = {
  href: string;
  label: string;
  icon: React.ElementType;
  moduleKey?: string;   // matches WorkerModules fields; undefined = always shown
};

// Items are shown in priority order.
// Disabled modules will render greyed-out (still visible but non-clickable)
// until the corresponding sprint builds the page.
const WORKER_NAV: WorkerNavItem[] = [
  { href: "/offers", label: "Mein Einstieg", icon: CheckSquare },
  { href: "/worker",               label: "Dashboard",     icon: LayoutDashboard },
  { href: "/worker/interviews",    label: "Interviews",    icon: Video },
  { href: "/worker/time",          label: "Zeiterfassung", icon: Clock,            moduleKey: "timetracking" },
  { href: "/worker/schedule",      label: "Einsatzplan",   icon: CalendarDays,     moduleKey: "schedule" },
  { href: "/worker/messages",      label: "Nachrichten",   icon: MessageSquare,    moduleKey: "messages" },
  { href: "/worker/documents",     label: "Dokumente",     icon: FolderOpen,       moduleKey: "documents" },
  { href: "/worker/absences",      label: "Abwesenheiten", icon: UtensilsCrossed,  moduleKey: "absences" },
  { href: "/worker/equipment",     label: "Ausrüstung",    icon: Wrench,           moduleKey: "equipment" },
  { href: "/worker/tasks",         label: "Aufgaben",      icon: CheckSquare,      moduleKey: "tasks" },
  { href: "/worker/payroll",       label: "Lohn",          icon: Receipt,          moduleKey: "payroll" },
  { href: "/worker/tickets",       label: "Tickets",       icon: Ticket,           moduleKey: "tickets" },
  { href: "/worker/profile",       label: "Profil",        icon: User,             moduleKey: "profile_selfservice" },
];

const STORAGE_KEY = "worker-sidebar-collapsed";

interface WorkerSidebarProps {
  /** Active modules from /worker/modules – if undefined all shown active */
  activeModules?: Record<string, boolean>;
  collapsed?: boolean;
  onToggle?: (collapsed: boolean) => void;
  unreadMessages?: number;
}

export function WorkerSidebar({ activeModules, collapsed: collapsedProp, onToggle, unreadMessages = 0 }: WorkerSidebarProps = {}) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useStoredBoolean(STORAGE_KEY);

  // controlled mode: use prop; uncontrolled: use local state + localStorage
  const isControlled = collapsedProp !== undefined;
  const isCollapsed = isControlled ? collapsedProp : collapsed;


  function toggle() {
    const next = !isCollapsed;
    if (isControlled) {
      onToggle?.(next);
    } else {
      setCollapsed(next);
    }
  }

  function isActive(href: string) {
    if (href === "/worker") return pathname === "/worker";
    return pathname.startsWith(href);
  }

  function isEnabled(moduleKey: string | undefined): boolean {
    if (!moduleKey || !activeModules) return true;
    return activeModules[moduleKey] !== false;
  }

  return (
    <aside
      className={`
        fixed left-0 top-14 z-40 flex h-[calc(100vh-3.5rem)] flex-col
        border-r border-gray-200 bg-white transition-all duration-200
        ${isCollapsed ? "w-14" : "w-52"}
      `}
    >
      {/* Toggle */}
      <button
        onClick={toggle}
        className="flex min-h-11 items-center justify-center border-b border-gray-100 text-gray-600 hover:text-gray-900 transition-colors"
        aria-label={isCollapsed ? "Navigation aufklappen" : "Navigation einklappen"}
        aria-expanded={!isCollapsed}
        title={isCollapsed ? "Aufklappen" : "Einklappen"}
      >
        {isCollapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
      </button>

      <nav className="flex flex-col gap-0.5 overflow-y-auto overflow-x-hidden p-1.5 flex-1">
        {WORKER_NAV.map(({ href, label, icon: Icon, moduleKey }) => {
          const active = isActive(href);
          const enabled = isEnabled(moduleKey);

          if (!enabled) return null; // hide disabled modules

          return (
            <div key={href} className="relative group">
              <Link
                href={href}
                aria-label={label}
                aria-current={active ? "page" : undefined}
                className={`
                  flex min-h-11 items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors
                  ${active
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                  }
                `}
              >
                <span className="relative shrink-0">
                  <Icon
                    size={17}
                    className={active ? "text-blue-600" : "text-gray-400 group-hover:text-gray-600"}
                  />
                  {moduleKey === "messages" && unreadMessages > 0 && (
                    <span className="absolute -right-1.5 -top-1.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-blue-600 text-[9px] font-bold text-white">
                      {unreadMessages > 9 ? "9+" : unreadMessages}
                    </span>
                  )}
                </span>
                {!isCollapsed && (
                  <span className="flex-1 flex items-center justify-between truncate">
                    <span className="truncate">{label}</span>
                    {moduleKey === "messages" && unreadMessages > 0 && (
                      <span className="ml-1 shrink-0 rounded-full bg-blue-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                        {unreadMessages > 9 ? "9+" : unreadMessages}
                      </span>
                    )}
                  </span>
                )}
              </Link>

              {isCollapsed && (
                <div className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-xs text-white opacity-0 group-hover:opacity-100 transition-opacity">
                  {label}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      {/* Tenant badge at bottom */}
      {!isCollapsed && (
        <div className="border-t border-gray-100 px-3 py-2">
          <p className="text-xs text-gray-400 truncate">Worker Portal</p>
        </div>
      )}
    </aside>
  );
}
