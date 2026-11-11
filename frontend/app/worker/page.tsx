"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Clock,
  CalendarDays,
  MessageSquare,
  FolderOpen,
  UtensilsCrossed,
  Wrench,
  CheckSquare,
  Receipt,
  Ticket,
  User,
  AlertCircle,
} from "lucide-react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { workerApi, ApiError } from "@/lib/api";
import type { WorkerMeRead } from "@/lib/api";

type ModuleTile = {
  href: string;
  label: string;
  desc: string;
  icon: React.ElementType;
  color: string;
  moduleKey: keyof WorkerMeRead["active_modules"];
};

const TILES: ModuleTile[] = [
  { href: "/worker/time",      label: "Zeiterfassung",  desc: "Stunden erfassen & einreichen",     icon: Clock,             color: "text-blue-600 bg-blue-50",     moduleKey: "timetracking" },
  { href: "/worker/schedule",  label: "Einsatzplan",    desc: "Schichten & Einsätze im Überblick", icon: CalendarDays,      color: "text-blue-600 bg-blue-50", moduleKey: "schedule" },
  { href: "/worker/messages",  label: "Nachrichten",    desc: "Disponent & Team kontaktieren",     icon: MessageSquare,     color: "text-violet-600 bg-violet-50", moduleKey: "messages" },
  { href: "/worker/documents", label: "Dokumente",      desc: "Verträge & Unterlagen einsehen",    icon: FolderOpen,        color: "text-amber-600 bg-amber-50",   moduleKey: "documents" },
  { href: "/worker/absences",  label: "Abwesenheiten",  desc: "Urlaub & Krankmeldungen",           icon: UtensilsCrossed,   color: "text-red-600 bg-red-50",       moduleKey: "absences" },
  { href: "/worker/equipment", label: "Ausrüstung",     desc: "Ausgeliehene Geräte & Kleidung",   icon: Wrench,            color: "text-orange-600 bg-orange-50", moduleKey: "equipment" },
  { href: "/worker/tasks",     label: "Aufgaben",       desc: "Offene To-dos & Onboarding",        icon: CheckSquare,       color: "text-teal-600 bg-teal-50",     moduleKey: "tasks" },
  { href: "/worker/payroll",   label: "Lohn",           desc: "Stunden & Abrechnungen",            icon: Receipt,           color: "text-green-600 bg-green-50",   moduleKey: "payroll" },
  { href: "/worker/tickets",   label: "Tickets",        desc: "Probleme & Anfragen melden",        icon: Ticket,            color: "text-pink-600 bg-pink-50",     moduleKey: "tickets" },
  { href: "/worker/profile",   label: "Profil",         desc: "Stammdaten & Qualifikationen",      icon: User,              color: "text-gray-600 bg-gray-100",    moduleKey: "profile_selfservice" },
];

const EMPLOYMENT_LABELS: Record<string, string> = {
  fulltime: "Vollzeit",
  parttime: "Teilzeit",
  minijob: "Minijob",
  temp: "Zeitarbeit",
};

export default function WorkerDashboard() {
  const router = useRouter();
  const [me, setMe] = useState<WorkerMeRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }

    workerApi.me(token)
      .then(setMe)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          setError("Dein Worker-Zugang ist deaktiviert. Bitte wende dich an deinen Disponenten.");
        } else {
          router.replace("/login");
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  if (error) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-16 text-center">
        <AlertCircle size={40} className="mx-auto mb-4 text-red-400" />
        <p className="text-sm text-gray-600">{error}</p>
      </main>
    );
  }

  if (!me) return null;

  const enabledTiles = TILES.filter((t) => me.active_modules[t.moduleKey] !== false);

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">
          Hallo{me.full_name ? `, ${me.full_name.split(" ")[0]}` : ""}!
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          {EMPLOYMENT_LABELS[me.employment_type] ?? me.employment_type} · Worker-Portal
        </p>
      </div>

      {/* Module grid */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {enabledTiles.map((tile) => {
          const Icon = tile.icon;
          const [iconColor, bgColor] = tile.color.split(" ");
          return (
            <Link
              key={tile.href}
              href={tile.href}
              className="group flex flex-col gap-3 rounded-xl border border-gray-200 bg-white p-5 hover:shadow-md hover:border-gray-300 transition-all"
            >
              <span className={`inline-flex h-10 w-10 items-center justify-center rounded-lg ${bgColor}`}>
                <Icon size={20} className={iconColor} />
              </span>
              <div>
                <p className="text-sm font-semibold text-gray-900 group-hover:text-blue-700 transition-colors">
                  {tile.label}
                </p>
                <p className="mt-0.5 text-xs text-gray-400 leading-relaxed">{tile.desc}</p>
              </div>
            </Link>
          );
        })}
      </div>
    </main>
  );
}
