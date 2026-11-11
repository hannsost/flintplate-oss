"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { authApi } from "@/lib/api";
import { PortalFrame } from "@/components/layout/PortalFrame";
import { Navbar } from "@/components/layout/Navbar";
import { Sidebar } from "@/components/layout/Sidebar";
import { useUnreadMessages } from "@/lib/useUnreadMessages";

const SIDEBAR_KEY = "sidebar-collapsed";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [allowed, setAllowed] = useState(false);
  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    authApi.me(token).then(user => {
      if (user.role === "admin" && !user.tenant_id) setAllowed(true);
      else router.replace(user.role === "worker" ? "/worker" : ["admin", "recruiter"].includes(user.role) ? "/dashboard" : "/profile");
    }).catch(() => router.replace("/login"));
  }, [router]);
  const unreadMessages = useUnreadMessages("recruiter");


  if (!allowed) return <p role="status" className="p-8 text-sm text-gray-600">Zugriff wird geprüft …</p>;

  return (
    <>
      <Navbar />
      <PortalFrame storageKey={SIDEBAR_KEY} sidebar={(collapsed, onToggle) => (
        <Sidebar isAdmin={true} collapsed={collapsed} onToggle={onToggle} unreadMessages={unreadMessages} />
      )}>{children}</PortalFrame>
    </>
  );
}
