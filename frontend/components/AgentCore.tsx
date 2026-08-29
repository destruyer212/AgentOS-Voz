import { Database, RadioTower, ShieldCheck } from "lucide-react";
import { NeonVoiceCore } from "./NeonVoiceCore";

interface AgentCoreProps {
  productsCount: number;
  lowStock: number;
}

export function AgentCore({ productsCount, lowStock }: AgentCoreProps) {
  const systems = [
    { label: "Voz", value: "Operativo", icon: RadioTower },
    { label: "Base de datos", value: `${productsCount} items`, icon: Database },
    { label: "Stock", value: lowStock === 0 ? "Estable" : `${lowStock} alertas`, icon: ShieldCheck },
  ];

  return (
    <section className="relative flex min-h-[210px] flex-col items-center justify-center overflow-hidden border border-hud-500/20 bg-surface-900/55 px-5 py-6 shadow-hud backdrop-blur-md lg:row-span-1">
      <div className="absolute inset-0 opacity-25">
        <div className="hud-radar-sweep absolute left-1/2 top-1/2 h-52 w-52 -translate-x-1/2 -translate-y-1/2 rounded-full" />
      </div>

      <div className="relative flex h-48 w-48 items-center justify-center">
        <NeonVoiceCore size="md" label="Nucleo animado del agente de voz" />
        <div className="absolute bottom-7 z-0 border border-accent-teal/25 bg-surface-950/45 px-2.5 py-1 shadow-[0_0_18px_rgba(45,212,191,0.16)] backdrop-blur-[2px]">
          <span className="font-mono text-[9px] uppercase tracking-[0.24em] text-accent-teal/85">Online</span>
        </div>
      </div>

      <div className="relative mt-3 text-center">
        <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-hud-400">Agente de voz</p>
        <p className="mt-1 text-sm font-semibold text-white">Operación activa</p>
      </div>

      <div className="relative mt-5 grid w-full grid-cols-3 gap-2">
        {systems.map((system) => {
          const Icon = system.icon;
          return (
            <div key={system.label} className="border border-surface-700/80 bg-surface-950/55 px-2.5 py-2">
              <div className="flex items-center gap-1.5 text-slate-500">
                <Icon size={12} className="text-hud-400" />
                <span className="truncate font-mono text-[9px] uppercase tracking-[0.12em]">{system.label}</span>
              </div>
              <p className="mt-1 truncate text-xs font-medium text-slate-200">{system.value}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
