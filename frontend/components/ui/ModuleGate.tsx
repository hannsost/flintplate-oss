"use client";

/**
 * ModuleGate – renders children only if the given module is enabled for the current tenant.
 *
 * Usage:
 *   <ModuleGate modules={modules} moduleKey={MODULE_KEYS.AI_COVER_LETTER}>
 *     <GenerateCoverLetterButton />
 *   </ModuleGate>
 *
 *   // With fallback:
 *   <ModuleGate modules={modules} moduleKey="map_view" fallback={<UpgradeHint module="Kartenansicht" />}>
 *     <MapView />
 *   </ModuleGate>
 */

import { Lock } from "lucide-react";
import { hasModule } from "@/lib/modules";

interface Props {
  modules: string[];
  moduleKey: string;
  /** What to render when module is disabled. Defaults to null (nothing). */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

export function ModuleGate({ modules, moduleKey, fallback = null, children }: Props) {
  if (hasModule(modules, moduleKey)) return <>{children}</>;
  return <>{fallback}</>;
}

/** Small inline badge shown when a feature is not available in the current plan. */
export function ModuleLocked({ name }: { name: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 text-xs text-gray-400 bg-gray-100 px-2 py-1 rounded-md cursor-not-allowed select-none"
      title={`${name} ist in deinem aktuellen Plan nicht verfügbar`}
    >
      <Lock size={11} /> {name}
    </span>
  );
}

/** Full-width upgrade hint block for larger gated areas. */
export function ModuleUpgradeHint({ name, category }: { name: string; category?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-6 border-2 border-dashed border-gray-200 rounded-xl bg-gray-50 text-center">
      <Lock size={32} className="text-gray-300 mb-3" />
      <p className="font-semibold text-gray-700">{name} nicht verfügbar</p>
      <p className="text-sm text-gray-400 mt-1">
        Dieses Feature ist im aktuellen Plan nicht aktiv.
        {category && ` Kategorie: ${category}`}
      </p>
      <p className="text-xs text-blue-500 mt-3">
        Wende dich an deinen Administrator, um das Modul zu aktivieren.
      </p>
    </div>
  );
}
