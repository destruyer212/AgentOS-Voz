"use client";

import { PhoneIncoming, X } from "lucide-react";
import Link from "next/link";
import { useActiveCalls } from "./ActiveCallsProvider";

/**
 * Stack de notificaciones flotante, visible en cualquier pantalla del panel:
 * apenas el backend reporta una conversacion "active" que no existia en el
 * sondeo anterior, aparece aca con un link directo al flujo en vivo de esa
 * llamada (/llamadas/[id]). Vive montado una sola vez en el layout raiz.
 */
export function IncomingCallToasts() {
  const { incoming, dismiss } = useActiveCalls();

  if (incoming.length === 0) return null;

  return (
    <div className="pointer-events-none fixed right-5 top-5 z-50 flex w-[340px] max-w-[calc(100vw-2.5rem)] flex-col gap-3">
      {incoming.map((call) => (
        <div
          key={call.id}
          className="hud-toast-in pointer-events-auto relative overflow-hidden border border-hud-400/50 bg-surface-950/95 p-4 shadow-hud backdrop-blur-xl"
          style={{
            clipPath: "polygon(0 10px, 10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%)",
          }}
        >
          <div className="hud-scanline pointer-events-none absolute inset-0" aria-hidden />
          <div className="relative flex items-start gap-3">
            <div className="relative flex h-10 w-10 shrink-0 items-center justify-center border border-hud-400/50 bg-hud-500/15 text-hud-300">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-hud-400/25" />
              <PhoneIncoming size={18} className="relative" />
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-hud-400 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-hud-400" />
                </span>
                <p className="font-mono text-[10px] font-medium uppercase tracking-[0.22em] text-hud-300">
                  Llamada entrante
                </p>
              </div>
              <p className="mt-1.5 truncate text-sm font-semibold text-white">
                {call.customer_name ?? call.customer_phone ?? "Cliente nuevo"}
              </p>
              {call.customer_name && call.customer_phone && (
                <p className="truncate font-mono text-xs text-slate-500">{call.customer_phone}</p>
              )}

              <Link
                href={`/llamadas/${encodeURIComponent(call.id)}`}
                className="mt-2.5 inline-flex items-center gap-1.5 border border-hud-500/30 bg-hud-500/10 px-2.5 py-1.5 font-mono text-[11px] font-medium uppercase tracking-wide text-hud-300 transition-colors hover:bg-hud-500/20"
                onClick={() => dismiss(call.id)}
              >
                Ver flujo en vivo →
              </Link>
            </div>

            <button
              type="button"
              onClick={() => dismiss(call.id)}
              className="text-slate-600 transition-colors hover:text-slate-300"
              aria-label="Descartar notificación"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
