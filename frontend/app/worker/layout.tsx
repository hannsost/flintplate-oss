"use client";

import { useEffect, useState } from "react";
import { PortalFrame } from "@/components/layout/PortalFrame";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogOut } from "lucide-react";
import { auth } from "@/lib/auth";
import { workerApi } from "@/lib/api";
import { WorkerSidebar } from "@/components/layout/WorkerSidebar";
import { WorkspaceLogo } from "@/components/layout/WorkspaceLogo";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { clearModuleCache } from "@/lib/modules";
import { useUnreadMessages } from "@/lib/useUnreadMessages";

const SIDEBAR_KEY = "worker-sidebar-collapsed";

export default function WorkerLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [activeModules, setActiveModules] = useState<Record<string, boolean> | undefined>(undefined);
  const unreadMessages = useUnreadMessages("worker");


  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }

    workerApi.modules(token)
      .then((mods) => setActiveModules(mods as unknown as Record<string, boolean>))
      .catch(() => setActiveModules({}));
  }, [router]);

  function handleLogout() {
    auth.clear();
    clearModuleCache();
    router.push("/login");
  }

  return (
    <>
      {/* Navbar */}
      <header className="sticky top-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur-sm">
        <div className="flex h-14 items-center justify-between gap-3 px-4">
          <Link href="/worker" className="flex min-h-11 min-w-0 items-center gap-2">
            <WorkspaceLogo />
            <span className="hidden shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 sm:inline">
              Worker
            </span>
          </Link>

          <div className="flex shrink-0 items-center gap-2">
            <NotificationBell />
            <button
              onClick={handleLogout}
              className="flex min-h-11 items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:border-gray-300 hover:text-gray-900 transition-colors"
            >
              <LogOut size={14} />
              Abmelden
            </button>
          </div>
        </div>
      </header>

      <PortalFrame storageKey={SIDEBAR_KEY} sidebar={(collapsed, onToggle) => (
        <WorkerSidebar activeModules={activeModules} collapsed={collapsed} onToggle={onToggle} unreadMessages={unreadMessages} />
      )}>{children}</PortalFrame>
    </>
  );
}
