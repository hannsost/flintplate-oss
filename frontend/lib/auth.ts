import { clearModuleCache } from "./modules";
import { AUTH_CHANGED_EVENT, clearOrderDrafts } from "./flintplate-drafts";

/**
 * localStorage token management for palmscout frontend.
 * Server components must NOT call these — browser-only.
 */

const ACCESS_KEY = "palmscout_access_token";
const REFRESH_KEY = "palmscout_refresh_token";
const LEGACY_ACCESS_KEY = "hireos_access_token";
const LEGACY_REFRESH_KEY = "hireos_refresh_token";

function tokenPrincipal(token: string | null): string | null {
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return typeof payload.sub === "string" ? JSON.stringify([payload.tenant_id ?? null, payload.sub]) : null;
  } catch { return null; }
}

function migrateSession() {
  if (!localStorage.getItem(ACCESS_KEY) && !localStorage.getItem(REFRESH_KEY)) {
    const access = localStorage.getItem(LEGACY_ACCESS_KEY);
    const refresh = localStorage.getItem(LEGACY_REFRESH_KEY);
    if (access && refresh) {
      localStorage.setItem(ACCESS_KEY, access);
      localStorage.setItem(REFRESH_KEY, refresh);
    }
  }
  localStorage.removeItem(LEGACY_ACCESS_KEY);
  localStorage.removeItem(LEGACY_REFRESH_KEY);
}

export const auth = {
  setTokens(access: string, refresh: string) {
    const changed = tokenPrincipal(auth.getAccess()) !== tokenPrincipal(access);
    if (changed) clearOrderDrafts();
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
    localStorage.removeItem(LEGACY_ACCESS_KEY);
    localStorage.removeItem(LEGACY_REFRESH_KEY);
    if (changed) window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  },

  getAccess(): string | null {
    migrateSession();
    return localStorage.getItem(ACCESS_KEY);
  },

  getRefresh(): string | null {
    migrateSession();
    return localStorage.getItem(REFRESH_KEY);
  },

  clear() {
    clearModuleCache();
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(LEGACY_ACCESS_KEY);
    localStorage.removeItem(LEGACY_REFRESH_KEY);
    clearOrderDrafts();
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  },

  /** Alias for getAccess() – preferred in most components */
  getToken(): string | null {
    return auth.getAccess();
  },

  isLoggedIn(): boolean {
    return !!auth.getAccess();
  },

  /** Decode JWT payload without verification (browser-side, claims are trusted from server) */
  getUser(): { sub: string; role: string; tenant_id: string | null } | null {
    const token = auth.getAccess();
    if (!token) return null;
    try {
      const parts = token.split(".");
      if (parts.length !== 3) return null;
      const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
      return {
        sub: payload.sub ?? "",
        role: payload.role ?? "candidate",
        tenant_id: payload.tenant_id ?? null,
      };
    } catch {
      return null;
    }
  },
};
