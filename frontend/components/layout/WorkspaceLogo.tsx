"use client";
import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { brandingApi, type WorkspaceBranding } from "@/lib/workspace-branding";

export function WorkspaceLogo() {
  const [branding, setBranding] = useState<WorkspaceBranding | null>(null);
  useEffect(() => {
    const token = auth.getAccess(); if (!token) return;
    let current = true;
    const refresh = () => brandingApi.get(auth.getAccess() ?? token).then(b => { if (current) setBranding(b); }).catch(() => { if (current) setBranding(null); });
    void refresh(); window.addEventListener("palmscout-branding-changed", refresh);
    return () => { current = false; window.removeEventListener("palmscout-branding-changed", refresh); };
  }, []);
  return <span className="flex min-w-0 items-center gap-2">
    {branding?.logo_url && <img src={branding.logo_url} alt="" referrerPolicy="no-referrer" className="h-8 max-w-12 shrink-0 object-contain sm:max-w-20" />}
    <span className="max-w-36 truncate text-lg font-bold sm:max-w-64" style={{ borderBottom: branding ? `3px solid ${branding.primary_color}` : undefined }}>{branding?.brand_name ?? "FlintPlate"}</span>
  </span>;
}
