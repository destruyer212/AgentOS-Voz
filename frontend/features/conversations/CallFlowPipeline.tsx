"use client";

import { CheckCircle2, ClipboardList, PhoneCall, PhoneOff, ShieldCheck, ShoppingCart } from "lucide-react";
import type { ComponentType } from "react";
import { CALL_STAGE_LABEL, callStage, type CallStageKey } from "@/lib/format";

const STEP_KEYS: CallStageKey[] = ["connected", "choosing", "details", "confirming", "confirmed"];

const STEP_ICON: Record<CallStageKey, ComponentType<{ size?: number; className?: string }>> = {
  connected: PhoneCall,
  choosing: ShoppingCart,
  details: ClipboardList,
  confirming: ShieldCheck,
  confirmed: CheckCircle2,
  ended: PhoneOff,
};

/**
 * Flujo grafico en tiempo real de una conversacion: en que etapa real esta
 * (segun el backend, no adivinado) -- conectada, eligiendo productos,
 * completando datos, confirmando, o cerrada. Vive en la pagina de detalle
 * de la llamada, refrescada por LiveRefresher mientras siga activa.
 */
export function CallFlowPipeline({
  status,
  detailStatus,
  outcome,
}: {
  status: string;
  detailStatus: string | null;
  outcome: string | null;
}) {
  const stage = callStage({ status, detail_status: detailStatus, outcome });
  const isEnded = stage.key === "ended";
  const isLive = status !== "closed";

  return (
    <div className="relative overflow-hidden rounded-xl border border-surface-700 bg-surface-900 p-5">
      {isLive && (
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-brand-500/0 via-brand-500/[0.06] to-brand-500/0" />
      )}

      <div className="relative mb-4 flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Flujo de la llamada</p>
        {isLive ? (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-brand-400">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-brand-400" />
            </span>
            En vivo
          </span>
        ) : (
          <span className="text-xs font-medium text-slate-500">Finalizada</span>
        )}
      </div>

      <div className="relative flex items-center">
        {STEP_KEYS.map((key, i) => {
          const isLast = i === STEP_KEYS.length - 1;
          const reached = i <= stage.index;
          const isCurrent = i === stage.index && !isEnded;
          const Icon = isLast && isEnded ? STEP_ICON.ended : STEP_ICON[key];
          const label = isLast && isEnded ? CALL_STAGE_LABEL.ended : CALL_STAGE_LABEL[key];

          return (
            <div key={key} className={`flex items-center ${isLast ? "" : "flex-1"}`}>
              <div className="flex flex-col items-center gap-2">
                <div
                  className={[
                    "flex h-9 w-9 items-center justify-center rounded-full border transition-all duration-500",
                    isLast && isEnded
                      ? "border-accent-rose/40 bg-accent-rose/10 text-accent-rose"
                      : reached
                        ? "border-brand-400/50 bg-brand-500/15 text-brand-400"
                        : "border-surface-600 bg-surface-800 text-slate-600",
                    isCurrent ? "shadow-[0_0_0_4px_rgba(109,109,247,0.15)]" : "",
                  ].join(" ")}
                >
                  <Icon size={16} className={isCurrent ? "animate-pulse-slow" : ""} />
                </div>
                <span
                  className={[
                    "hidden text-center text-[11px] leading-tight sm:block",
                    isLast && isEnded
                      ? "text-accent-rose"
                      : reached
                        ? "text-slate-300"
                        : "text-slate-600",
                    isCurrent ? "font-medium" : "",
                  ].join(" ")}
                  style={{ maxWidth: "5.5rem" }}
                >
                  {label}
                </span>
              </div>

              {!isLast && (
                <div className="mx-1 h-px flex-1 self-start pt-4">
                  <div className="h-px w-full bg-surface-600">
                    <div
                      className="h-px bg-gradient-to-r from-brand-500 to-brand-400 transition-all duration-700"
                      style={{ width: i < stage.index ? "100%" : "0%" }}
                    />
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
