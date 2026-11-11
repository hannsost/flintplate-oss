"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogOut, Headphones } from "lucide-react";
import { auth } from "@/lib/auth";
import { authApi } from "@/lib/api";
import { wsClient } from "@/lib/websocket";

export default function SupportLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }

    // Connect WS immediately using JWT claims (no network round-trip needed),
    // so the agent's session_join / agent_ready are never sent on a still-connecting socket.
    const user = auth.getUser();
    if (user?.role !== "support") { router.replace("/login"); return; }
    wsClient.connect(token);

    // Server-side role verification in the background
    authApi.me(token).then((u) => {
      if (u.role !== "support") { wsClient.disconnect(); router.replace("/login"); }
    }).catch(() => { wsClient.disconnect(); router.replace("/login"); });

    return () => wsClient.disconnect();
  }, [router]);

  function handleLogout() {
    auth.clear();
    router.push("/login");
  }

  return (
    <>
      <header className="sticky top-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur-sm">
        <div className="flex h-14 items-center justify-between px-6">
          <Link href="/support" className="flex items-center gap-2">
            <span className="text-lg font-bold tracking-tight">
              palm<span className="text-blue-600">scout</span>
            </span>
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 flex items-center gap-1">
              <Headphones size={10} /> Support
            </span>
          </Link>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:border-gray-300 hover:text-gray-900 transition-colors"
          >
            <LogOut size={14} />
            Abmelden
          </button>
        </div>
      </header>
      <main>{children}</main>
    </>
  );
}
