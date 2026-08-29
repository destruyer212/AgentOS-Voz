import { CalendarClock, Store } from "lucide-react";
import { HudPanel } from "./HudPanel";
import type { BusinessInfoOut } from "@/lib/types";

/**
 * Detalles de la empresa: nombre + horario real de atencion. Mismo dato
 * que usa el agente para responder "atienden hoy?" por telefono (ver
 * app/domain/business_hours.py en el backend) -- una sola fuente de
 * verdad, nunca dos horarios que puedan desincronizarse.
 */
export function BusinessInfoCard({ info }: { info: BusinessInfoOut }) {
  return (
    <HudPanel className="p-5">
      <div className="flex items-center gap-2">
        <Store size={15} className="text-hud-400" />
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Datos del negocio</p>
      </div>

      <p className="mt-3 text-lg font-semibold text-white">{info.restaurant_name}</p>

      <div className="mt-4 flex items-center gap-2">
        <span
          className={`relative flex h-2 w-2 shrink-0 ${info.is_open ? "" : "opacity-60"}`}
        >
          {info.is_open && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-teal opacity-75" />
          )}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${
              info.is_open ? "bg-accent-teal" : "bg-accent-rose"
            }`}
          />
        </span>
        <span className={`text-sm font-medium ${info.is_open ? "text-accent-teal" : "text-accent-rose"}`}>
          {info.is_open ? "Abierto ahora" : "Cerrado ahora"}
        </span>
      </div>

      <div className="mt-3 flex items-center gap-2 text-sm text-slate-400">
        <CalendarClock size={14} className="shrink-0 text-slate-500" />
        <span>
          Todos los días, {info.open_time} – {info.close_time}
        </span>
      </div>
      <p className="mt-1 pl-[22px] text-xs capitalize text-slate-600">Hoy es {info.day_name}</p>
    </HudPanel>
  );
}
