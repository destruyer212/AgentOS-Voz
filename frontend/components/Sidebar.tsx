"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Bot,
  CalendarClock,
  ChefHat,
  ClipboardList,
  ConciergeBell,
  LayoutDashboard,
  LogOut,
  Phone,
  Radio,
  Receipt,
  SignalHigh,
  ScrollText,
  Store,
  Trophy,
  UtensilsCrossed,
  Users,
} from "lucide-react";
import type { ComponentType } from "react";
import { logoutAction } from "@/app/login/actions";
import { ROLE_LABEL, type Role } from "@/lib/auth-shared";
import { useActiveCalls } from "./ActiveCallsProvider";

interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  // "/" y "/contabilidad" necesitan match exacto -- si no, "startsWith"
  // marcaria el link de Dashboard/Resumen como activo en CUALQUIER
  // subruta (ej. /contabilidad/productos tambien "empieza con" /contabilidad).
  exact?: boolean;
}

interface NavSection {
  title: string | null;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: null,
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
      { href: "/agente", label: "Agente", icon: Bot },
      { href: "/llamadas", label: "Llamadas", icon: Phone },
      { href: "/pedidos", label: "Pedidos", icon: ClipboardList },
      { href: "/cocina", label: "Cocina", icon: ChefHat },
      { href: "/recepcion", label: "Recepción", icon: ConciergeBell },
      { href: "/productos", label: "Productos", icon: UtensilsCrossed },
      { href: "/clientes", label: "Clientes", icon: Users },
      { href: "/negocio", label: "Negocio", icon: Store },
      { href: "/auditoria", label: "Auditoría", icon: ScrollText },
    ],
  },
  {
    // Solo admin -- ver visibleNavSections abajo y canAccess en
    // lib/auth-shared.ts (cocina/recepcion no pueden entrar a /contabilidad
    // aunque escriban la URL a mano).
    title: "Contabilidad",
    items: [
      { href: "/contabilidad", label: "Resumen", icon: BarChart3, exact: true },
      { href: "/contabilidad/productos", label: "Productos", icon: UtensilsCrossed },
      { href: "/contabilidad/clientes", label: "Clientes", icon: Trophy },
      { href: "/contabilidad/canales", label: "Canales", icon: Radio },
      { href: "/contabilidad/horarios", label: "Horarios", icon: CalendarClock },
      { href: "/contabilidad/comprobantes", label: "Comprobantes", icon: Receipt },
    ],
  },
];

// El admin ve todo (incluidas Cocina, Recepcion y Contabilidad); cocina y
// recepcion solo tienen su propia pantalla en el menu -- el middleware ya
// les bloquea el resto (ver middleware.ts, lib/auth.ts), pero mostrarles
// links que igual no pueden abrir solo confunde. Las secciones que quedan
// sin items para ese rol no se muestran (ver el .filter de abajo).
function visibleNavSections(role: Role): NavSection[] {
  if (role === "admin") return NAV_SECTIONS;
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => item.href === `/${role}`),
  })).filter((section) => section.items.length > 0);
}

export function Sidebar({ role }: { role: Role }) {
  const pathname = usePathname();
  const { activeCalls } = useActiveCalls();
  const liveCount = activeCalls.length;
  const sections = visibleNavSections(role);

  return (
    <aside className="relative z-20 flex h-full w-64 shrink-0 flex-col border-r border-hud-500/20 bg-surface-950/85 backdrop-blur-xl">
      <div className="pointer-events-none absolute inset-y-0 right-0 w-px bg-gradient-to-b from-transparent via-hud-400/50 to-transparent" />

      <div className="flex items-center gap-3 px-5 py-6">
        <div className="relative flex h-10 w-10 items-center justify-center border border-hud-400/40 bg-hud-500/10 shadow-hud">
          <span className="absolute inset-1 border border-hud-300/20" />
          <SignalHigh size={19} className="relative text-hud-300" />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold text-white">AgentOS Voz</p>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-hud-400/80">Command OS</p>
        </div>
      </div>

      <nav className="flex-1 space-y-4 overflow-y-auto px-3">
        {sections.map((section, sectionIdx) => (
          <div key={section.title ?? `section-${sectionIdx}`} className="space-y-1">
            {section.title && (
              <p className="px-3 pb-1 pt-2 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600">
                {section.title}
              </p>
            )}
            {section.items.map((item) => {
              const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`group relative flex items-center gap-3 px-3 py-2.5 text-sm font-medium transition-colors ${
                    active
                      ? "border border-hud-400/45 bg-hud-500/10 text-hud-300 shadow-hud"
                      : "border border-transparent text-slate-400 hover:border-hud-500/20 hover:bg-surface-800/70 hover:text-slate-200"
                  }`}
                  style={{
                    clipPath:
                      "polygon(0 8px, 8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%)",
                  }}
                >
                  {active && (
                    <span className="absolute -left-3 top-1/2 h-6 w-0.5 -translate-y-1/2 bg-hud-300 shadow-[0_0_12px_1px_rgba(77,216,240,0.9)]" />
                  )}
                  <Icon
                    size={17}
                    className={active ? "text-hud-300" : "text-slate-500 group-hover:text-hud-300"}
                  />
                  <span className="flex-1">{item.label}</span>
                  {item.href === "/llamadas" && liveCount > 0 && (
                    <span className="flex items-center gap-1 rounded-full border border-hud-400/50 bg-hud-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-hud-300">
                      <span className="relative flex h-1.5 w-1.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-hud-400 opacity-75" />
                        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-hud-400" />
                      </span>
                      {liveCount}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-hud-500/15 px-4 py-4">
        <div className="flex items-center gap-3 border border-surface-700/80 bg-surface-900/70 px-3 py-3">
          <span className="relative flex h-1.5 w-1.5 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-teal opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent-teal" />
          </span>
          <div className="min-w-0 flex-1 leading-tight">
            <p className="truncate text-xs font-medium text-slate-300">El Olivar Grill</p>
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{ROLE_LABEL[role]}</p>
          </div>
          <form action={logoutAction}>
            <button
              type="submit"
              title="Cerrar sesión"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-surface-700 hover:text-accent-rose"
            >
              <LogOut size={14} />
            </button>
          </form>
        </div>
      </div>
    </aside>
  );
}
