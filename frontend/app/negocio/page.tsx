import { CalendarClock, Database, RadioTower, Settings2, Store } from "lucide-react";
import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { BusinessInfoCard } from "@/components/BusinessInfoCard";
import { HudPanel } from "@/components/HudPanel";
import { NeonVoiceCore } from "@/components/NeonVoiceCore";
import { PageHeader } from "@/components/PageHeader";
import { ApiError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Negocio" };

export default async function NegocioPage() {
  try {
    const info = await api.system.businessInfo();

    return (
      <div>
        <PageHeader
          title="Negocio"
          description="Configuración visible del restaurante que usa el agente para responder horarios y contexto operativo."
        />

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="space-y-6">
            <BusinessInfoCard info={info} />

            <HudPanel className="p-5">
              <div className="flex items-center gap-2">
                <Settings2 size={15} className="text-hud-400" />
                <p className="font-mono text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
                  Próximo control
                </p>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-slate-400">
                Esta pantalla ya está separada del dashboard. El siguiente paso natural es permitir editar nombre,
                horarios, zonas de reparto y mensajes del agente desde aquí.
              </p>
            </HudPanel>
          </div>

          <HudPanel className="overflow-hidden p-6" glow>
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
              <div className="flex items-center justify-center">
                <NeonVoiceCore size="lg" label="Núcleo del negocio conectado al agente" />
              </div>

              <div className="flex flex-col justify-center">
                <p className="font-mono text-xs uppercase tracking-[0.24em] text-hud-300">Business Core</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">{info.restaurant_name}</h2>
                <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-400">
                  El agente usa esta fuente para saber si puede tomar pedidos, cómo contestar sobre horarios y qué
                  identidad mostrar en el panel.
                </p>

                <div className="mt-6 grid grid-cols-1 gap-3 2xl:grid-cols-3">
                  <BusinessSignal
                    icon={Store}
                    label="Local"
                    value={info.restaurant_name}
                    tone="hud"
                  />
                  <BusinessSignal
                    icon={CalendarClock}
                    label="Horario"
                    value={`${info.open_time} - ${info.close_time}`}
                    tone="teal"
                  />
                  <BusinessSignal
                    icon={RadioTower}
                    label="Estado"
                    value={info.is_open ? "Abierto" : "Cerrado"}
                    tone={info.is_open ? "teal" : "rose"}
                  />
                </div>

                <div className="mt-6 border border-surface-700 bg-surface-950/65 p-4">
                  <div className="flex items-center gap-2">
                    <Database size={15} className="text-hud-400" />
                    <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-slate-500">
                      Fuente actual
                    </p>
                  </div>
                  <p className="mt-2 text-sm text-slate-400">
                    Backend: reglas de horario del negocio. Hoy el frontend solo lo muestra; todavía no lo edita.
                  </p>
                </div>
              </div>
            </div>
          </HudPanel>
        </div>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Negocio" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}

function BusinessSignal({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Store;
  label: string;
  value: string;
  tone: "hud" | "teal" | "rose";
}) {
  const toneClass = {
    hud: "border-hud-500/25 text-hud-300",
    teal: "border-accent-teal/25 text-accent-teal",
    rose: "border-accent-rose/25 text-accent-rose",
  }[tone];

  return (
    <div className={`border bg-surface-950/65 p-3 ${toneClass}`}>
      <div className="flex items-center gap-2">
        <Icon size={14} />
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span>
      </div>
      <p className="mt-2 text-sm font-semibold leading-snug text-slate-100">{value}</p>
    </div>
  );
}
