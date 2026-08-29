"use client";

import { useEffect, useState } from "react";

function greetingForHour(hour: number): string {
  if (hour < 6) return "Buenas noches";
  if (hour < 12) return "Buenos días";
  if (hour < 19) return "Buenas tardes";
  return "Buenas noches";
}

/**
 * Hero del dashboard: saludo al admin + reloj en vivo. Es puramente
 * decorativo/ambiental (nada critico depende de la hora exacta del
 * navegador), asi que renderiza un placeholder estable en el server y
 * recien arranca el reloj al montar en el cliente -- evita el mismatch de
 * hidratacion entre la hora del server y la del navegador del usuario.
 */
export function DashboardHero({ restaurantName }: { restaurantName: string }) {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const greeting = now ? greetingForHour(now.getHours()) : "Hola";
  const time = now
    ? now.toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "--:--:--";
  const date = now
    ? now.toLocaleDateString("es-PE", { weekday: "long", day: "numeric", month: "long" })
    : "";

  return (
    <div className="relative mb-8 overflow-hidden rounded-xl border border-hud-500/20 bg-gradient-to-br from-surface-900 via-surface-900 to-hud-500/[0.06] px-6 py-6 shadow-hud">
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(34,200,230,0.6) 1px, transparent 1px), linear-gradient(90deg, rgba(34,200,230,0.6) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
        aria-hidden
      />
      <div className="relative flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-hud-400">
            AgentOS Voz · Consola de operaciones
          </p>
          <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-white">
            {greeting}, admin
            <span className="ml-1 inline-block animate-pulse text-hud-400">.</span>
          </h1>
          <p className="mt-1 text-sm capitalize text-slate-400">
            {date} — {restaurantName}
          </p>
        </div>
        <div className="text-right">
          <p className="font-mono text-3xl font-semibold tabular-nums text-hud-300">{time}</p>
          <p className="mt-0.5 inline-flex items-center gap-1.5 justify-end text-xs text-slate-500">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-teal opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent-teal" />
            </span>
            Sistema en línea
          </p>
        </div>
      </div>
    </div>
  );
}
