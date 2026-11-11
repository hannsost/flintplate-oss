"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PortalFrame } from "@/components/layout/PortalFrame";
import { auth } from "@/lib/auth";
import { authApi } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { Sidebar } from "@/components/layout/Sidebar";
import { useUnreadMessages } from "@/lib/useUnreadMessages";

const SIDEBAR_KEY = "sidebar-collapsed";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [isAdmin, setIsAdmin] = useState(false);
  const [ready, setReady] = useState(false);
  const unreadMessages = useUnreadMessages("recruiter");


  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    authApi.me(token).then((u) => {
      if (u.role === "admin" && !u.tenant_id) { router.replace("/admin"); return; }
      if (!["recruiter", "admin"].includes(u.role)) { router.replace(u.role === "worker" ? "/worker" : "/profile"); return; }
      if (!u.tenant_id) { router.replace("/register/recruiter"); return; }
      setIsAdmin(u.role === "admin"); setReady(true);
    }).catch(() => router.replace("/login"));
  }, [router]);

  if (!ready) return <p role="status" className="p-10 text-center text-slate-500">Arbeitsbereich wird geöffnet …</p>;

  return (
    <>
      <Navbar />
      <PortalFrame storageKey={SIDEBAR_KEY} sidebar={(collapsed, onToggle) => (
        <Sidebar isAdmin={isAdmin} collapsed={collapsed} onToggle={onToggle} unreadMessages={unreadMessages} />
      )}>{children}</PortalFrame>
    </>
  );
}
