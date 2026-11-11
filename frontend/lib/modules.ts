/**
 * Module awareness for feature-gating.
 *
 * Fetches active module keys from /users/my-modules and caches them
 * per session in localStorage. All AI features and premium modules
 * check this before rendering.
 */

const CACHE_TTL_MS = 5 * 60 * 1000;
// Never reuse entitlements across accounts, tenants or refreshed sessions.
let cache: { token: string; modules: string[]; fetchedAt: number } | null = null;

export const MODULE_KEYS = {
  AI_CV_PARSER: "ai_cv_parser",
  AI_COVER_LETTER: "ai_cover_letter",
  AI_INTERVIEW_PREP: "ai_interview_prep",
  AI_LINKEDIN_POST: "ai_linkedin_post",
  MAP_VIEW: "map_view",
  JOB_SCRAPER_IMPORT: "job_scraper_import",
  KANBAN_PIPELINE: "kanban_pipeline",
  INTERVIEW_SCHEDULING: "interview_scheduling",
  ANALYTICS_ADVANCED: "analytics_advanced",
  CONTENT_KIT: "content_kit",
  ZEITARBEIT_POOL: "zeitarbeit_pool",
  PARTNER_PORTAL: "partner_portal",
} as const;

export type ModuleKey = (typeof MODULE_KEYS)[keyof typeof MODULE_KEYS];

/** Fetch active modules from API and cache them. */
export async function fetchModules(token: string): Promise<string[]> {
  if (cache?.token === token && Date.now() - cache.fetchedAt < CACHE_TTL_MS) return cache.modules;
  const { request } = await import("@/lib/api");
  try {
    const modules = await request<unknown>("/users/my-modules", {}, token);
    const result = Array.isArray(modules) ? modules.filter((value): value is string => typeof value === "string") : [];
    cache = { token, modules: result, fetchedAt: Date.now() };
    return result;
  } catch {
    // A failed entitlement check must never grant paid capabilities.
    return [];
  }
}

/** Check a single module key against a fetched list. */
export function hasModule(modules: string[], key: string): boolean {
  return modules.includes(key);
}

/** Clear the module cache (call on logout). */
export function clearModuleCache(): void {
  cache = null;
  if (typeof window !== "undefined") localStorage.removeItem("hireos_modules");
}
