"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  ClipboardList,
  LayoutDashboard,
  Phone,
  ScrollText,
  UtensilsCrossed,
  Users,
} from "lucide-react";
import type { ComponentType } from "react";

interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/agente", label: "Agente", icon: Bot },
  { href: "/llamadas", label: "Llamadas", icon: Phone },
  { href: "/pedidos", label: "Pedidos", icon: ClipboardList },
  { href: "/productos", label: "Productos", icon: UtensilsCrossed },
  { href: "/clientes", label: "Clientes", icon: Users },
  { href: "/auditoria", label: "Auditoría", icon: ScrollText },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-surface-700 bg-surface-900">
      <div className="flex items-center gap-2.5 px-5 py-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-700 shadow-panel">
          <Bot size={18} className="text-white" />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold text-white">AgentOS Voz</p>
          <p className="text-xs text-slate-500">Panel de control</p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {NAV_ITEMS.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-brand-500/15 text-brand-400"
                  : "text-slate-400 hover:bg-surface-800 hover:text-slate-200"
              }`}
            >
              <Icon
                size={17}
                className={active ? "text-brand-400" : "text-slate-500 group-hover:text-slate-300"}
              />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-surface-700 px-4 py-4">
        <div className="flex items-center gap-2 rounded-lg bg-surface-800 px-3 py-2.5">
          <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent-teal" />
          <div className="min-w-0 leading-tight">
            <p className="truncate text-xs font-medium text-slate-300">tenant_demo</p>
            <p className="text-[11px] text-slate-500">Restaurante Demo</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
