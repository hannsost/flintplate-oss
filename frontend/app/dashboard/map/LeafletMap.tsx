"use client";

import { useEffect, useRef } from "react";
import type { MapAssignmentOut, MapWorkerOut } from "@/lib/api";
import "leaflet/dist/leaflet.css";

// Isochrone radii in metres per travel-time bucket
const ISOCHRONE_RADII: Record<string, number> = {
  "15 min": 8000,
  "30 min": 15000,
  "45 min": 22000,
  "60 min": 30000,
};
const ISOCHRONE_COLORS = ["#34d399", "#fbbf24", "#f97316", "#ef4444"];

function assignmentColor(status: string): string {
  switch (status) {
    case "active": return "#3b82f6";
    case "incoming": return "#f97316";
    case "closed": return "#6b7280";
    default: return "#8b5cf6";
  }
}

function workerColor(status: string): string {
  if (status === "red") return "#ef4444";
  if (status === "yellow") return "#f59e0b";
  return "#10b981";
}

function makeCircleMarker(L: typeof import("leaflet"), lat: number, lng: number, color: string, title: string) {
  return L.circleMarker([lat, lng], {
    radius: 10,
    fillColor: color,
    color: "#fff",
    weight: 2,
    opacity: 1,
    fillOpacity: 0.9,
  }).bindTooltip(title, { permanent: false, direction: "top" });
}

interface LeafletMapProps {
  assignments: MapAssignmentOut[];
  workers: MapWorkerOut[];
  isochroneKey: string | null;
  onSelectAssignment: (a: MapAssignmentOut) => void;
  onSelectWorker: (w: MapWorkerOut) => void;
}

export default function LeafletMap({
  assignments,
  workers,
  isochroneKey,
  onSelectAssignment,
  onSelectWorker,
}: LeafletMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const layersRef = useRef<any[]>([]);

  // Initialize map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    // Dynamic import to avoid SSR issues
    import("leaflet").then((L) => {
      // Fix default icon paths (broken in webpack bundles)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      const map = L.map(containerRef.current!, {
        center: [51.1657, 10.4515], // Central Germany
        zoom: 6,
        zoomControl: true,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map);

      mapRef.current = map;

      // Render markers after map is initialized
      renderMarkers(L, map);
    });

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render markers whenever data or filters change
  useEffect(() => {
    if (!mapRef.current) return;
    import("leaflet").then((L) => {
      renderMarkers(L, mapRef.current);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignments, workers, isochroneKey]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function renderMarkers(L: typeof import("leaflet"), map: any) {
    // Clear old layers
    layersRef.current.forEach((l) => map.removeLayer(l));
    layersRef.current = [];

    // Isochrone circles
    if (isochroneKey) {
      assignments.forEach((a) => {
        if (a.lat == null || a.lng == null) return;
        const entries = Object.entries(ISOCHRONE_RADII);
        entries.forEach(([key, radius], idx) => {
          if (isochroneKey !== "all" && key !== isochroneKey) return;
          const circle = L.circle([a.lat!, a.lng!], {
            radius,
            color: ISOCHRONE_COLORS[idx] ?? "#6b7280",
            fillColor: ISOCHRONE_COLORS[idx] ?? "#6b7280",
            fillOpacity: 0.07,
            weight: 1,
            opacity: 0.4,
          }).addTo(map);
          layersRef.current.push(circle);
        });
      });
    }

    // Assignment markers
    assignments.forEach((a) => {
      if (a.lat == null || a.lng == null) return;
      const marker = makeCircleMarker(L, a.lat, a.lng, assignmentColor(a.status), a.title);
      marker.on("click", () => onSelectAssignment(a));
      marker.addTo(map);
      layersRef.current.push(marker);
    });

    // Worker markers (smaller)
    workers.forEach((w) => {
      if (w.lat == null || w.lng == null) return;
      const marker = L.circleMarker([w.lat, w.lng], {
        radius: 7,
        fillColor: workerColor(w.aueg_status),
        color: "#fff",
        weight: 1.5,
        opacity: 1,
        fillOpacity: 0.85,
      }).bindTooltip(w.full_name ?? "Mitarbeiter", { permanent: false, direction: "top" });
      marker.on("click", () => onSelectWorker(w));
      marker.addTo(map);
      layersRef.current.push(marker);
    });
  }

  return <div ref={containerRef} className="w-full h-full" />;
}
