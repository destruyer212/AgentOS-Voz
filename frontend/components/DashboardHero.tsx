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
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const greeting = greetingForHour(now.getHours());
  const time = now.toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const date = now.toLocaleDateString("es-PE", { weekday: "long", day: "numeric", month: "long" });

  return (
    <div className="relative mb-6 overflow-hidden border border-hud-500/25 bg-surface-900/60 px-6 py-6 shadow-hud backdrop-blur-md">
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.09]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(77,216,240,0.75) 1px, transparent 1px), linear-gradient(90deg, rgba(77,216,240,0.65) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }}
        aria-hidden
      />
      <div className="pointer-events-none absolute left-0 top-0 h-px w-24 bg-hud-300" />
      <div className="pointer-events-none absolute bottom-0 right-0 h-px w-24 bg-hud-300" />

      <div className="relative flex flex-wrap items-center justify-between gap-5">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-hud-400">
            {restaurantName}
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-white">
            Consola de operaciones
            <span className="ml-1 inline-block animate-pulse text-hud-400">.</span>
          </h1>
          <p className="mt-2 text-sm capitalize text-slate-400" suppressHydrationWarning>
            {greeting}, admin · {date}
          </p>
        </div>

        <div className="min-w-[260px] border border-hud-500/20 bg-surface-950/55 px-5 py-4 text-right">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">Tiempo del sistema</p>
          <p className="mt-1 font-mono text-4xl font-semibold tabular-nums text-hud-300" suppressHydrationWarning>
            {time}
          </p>
          <p className="mt-1 inline-flex items-center justify-end gap-1.5 text-xs text-slate-500">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-teal opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent-teal" />
            </span>
            Sistema en linea
          </p>
        </div>
      </div>
    </div>
  );
}
