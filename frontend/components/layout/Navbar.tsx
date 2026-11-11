"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { LogOut, User, Briefcase, ClipboardList } from "lucide-react";
import { auth } from "@/lib/auth";
import { authApi } from "@/lib/api";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { brandingApi, type WorkspaceBranding } from "@/lib/workspace-branding";
import { clearModuleCache } from "@/lib/modules";

const CANDIDATE_NAV = [
  { href: "/profile", label: "Profil", icon: User },
  { href: "/jobs", label: "Jobs", icon: Briefcase },
  { href: "/applications", label: "Bewerbungen", icon: ClipboardList },
  { href: "/offers", label: "Angebote & Einstieg", icon: Briefcase },
];

const PORTAL_BADGE: Record<string, string> = {
  candidate:  "Kandidat",
  recruiter:  "Recruiting",
  worker: "Mitarbeitende",
  admin:      "Admin",
  headhunter: "Headhunter",
};

export function Navbar() {
  const router = useRouter();
  const pathname = usePathname();
  const [isVerified, setIsVerified] = useState(true);
  const [userEmail, setUserEmail] = useState("");
  const [resendSent, setResendSent] = useState(false);
  const [portalHome, setPortalHome] = useState("/profile");
  const [role, setRole] = useState<string | null>(null);

  const [branding, setBranding] = useState<WorkspaceBranding | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    let mounted = true;
    const refreshBranding = () => brandingApi.get(auth.getAccess() ?? token).then(b => { if (mounted) setBranding(b); }).catch(() => { if (mounted) setBranding(null); });
    window.addEventListener("palmscout-branding-changed", refreshBranding);
    authApi.me(token).then((u) => {
      if (!mounted) return;
      if (u.tenant_id) void refreshBranding();
      setIsVerified(u.is_verified ?? true);
      setUserEmail(u.email);
      setRole(u.role);
      setPortalHome(u.role === "admin" && !u.tenant_id ? "/admin" : ["admin", "recruiter"].includes(u.role) ? "/dashboard" : u.role === "worker" ? "/worker" : "/profile");
    }).catch(() => {});
    return () => { mounted = false; window.removeEventListener("palmscout-branding-changed", refreshBranding); };
  }, []);

  async function handleResendVerification() {
    if (!userEmail) return;
    await authApi.sendVerification(userEmail).catch(() => {});
    setResendSent(true);
  }

  function handleLogout() {
    auth.clear();
    clearModuleCache();
    router.push("/login");
  }

  return (
    <>
      {!isVerified && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-center text-sm text-amber-800">
          Bitte bestätige deine E-Mail-Adresse, um alle Funktionen nutzen zu können.{" "}
          {resendSent ? (
            <span className="font-medium text-amber-700">E-Mail gesendet!</span>
          ) : (
            <button
              onClick={handleResendVerification}
              className="font-medium underline hover:text-amber-900"
            >
              Erneut senden
            </button>
          )}
        </div>
      )}
      <header className="sticky top-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur-sm">
        <div className="flex h-14 items-center justify-between gap-3 px-4">
          <Link href={portalHome} className="flex min-h-11 min-w-0 items-center gap-2">
            {branding?.logo_url && <img src={branding.logo_url} alt="" referrerPolicy="no-referrer" className="h-8 max-w-12 shrink-0 object-contain sm:max-w-20" />}
            <span className="min-w-0 max-w-40 truncate text-lg font-bold tracking-tight sm:max-w-64" style={{ borderBottom: branding ? `3px solid ${branding.primary_color}` : undefined }}>
              {branding?.brand_name ?? "FlintPlate"}
            </span>
            {role && PORTAL_BADGE[role] && (
              <span className="hidden shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 sm:inline">
                {PORTAL_BADGE[role]}
              </span>
            )}
          </Link>

          {/* Candidate navigation */}
          {role === "candidate" && (
            <nav className="hidden items-center gap-1 mx-4 lg:flex">
              {CANDIDATE_NAV.map(({ href, label, icon: Icon }) => {
                const active = pathname === href || (href !== "/profile" && pathname.startsWith(href));
                return (
                  <Link
                    key={href}
                    href={href}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                      active
                        ? "bg-blue-50 text-blue-700"
                        : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                    }`}
                  >
                    <Icon size={15} />
                    {label}
                  </Link>
                );
              })}
            </nav>
          )}

          <div className="flex items-center gap-2 shrink-0">
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
        {role === "candidate" && (
          <nav aria-label="Kandidatennavigation" className="grid grid-cols-4 border-t px-2 lg:hidden">
            {CANDIDATE_NAV.map(({ href, label, icon: Icon }) => (
              <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined}
                className="flex min-h-14 min-w-0 flex-col items-center justify-center gap-1 px-1 text-center text-xs font-medium leading-4 text-slate-700">
                <Icon size={16} aria-hidden="true" />{label}
              </Link>
            ))}
          </nav>
        )}
      </header>
    </>
  );
}
