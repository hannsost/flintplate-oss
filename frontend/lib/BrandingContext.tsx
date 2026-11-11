"use client";

import { createContext, useContext } from "react";
import type { TenantBranding } from "@/lib/api";

export const BrandingContext = createContext<TenantBranding | null>(null);

export function useBranding(): TenantBranding {
  const ctx = useContext(BrandingContext);
  if (!ctx) throw new Error("useBranding must be used within BrandingProvider");
  return ctx;
}
