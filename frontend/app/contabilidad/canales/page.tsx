import { Hand, MessageSquare, PhoneCall, Smartphone } from "lucide-react";
import type { Metadata } from "next";
import type { ComponentType } from "react";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { HudPanel } from "@/components/HudPanel";
import { PageHeader } from "@/components/PageHeader";
import { parseAnalyticsRange, RangePicker } from "@/features/analytics/RangePicker";
import { ApiError, api } from "@/lib/api";
import { channelLabel, formatCurrency, formatPercent } from "@/lib/format";

export const metadata: Metadata = { title: "Contabilidad · Canales" };

const CHANNEL_ICON: Record<string, ComponentType<{ size?: number; className?: string }>> = {
  phone: PhoneCall,
  web: MessageSquare,
  whatsapp: Smartphone,
  manual: Hand,
};

const CHANNEL_ACCENT: Record<string, string> = {
  phone: "border-accent-amber/35 bg-accent-amber/10 text-accent-amber",
  web: "border-brand-400/35 bg-brand-500/10 text-brand-400",
  whatsapp: "border-accent-teal/35 bg-accent-teal/10 text-accent-teal",
  manual: "border-hud-400/35 bg-hud-500/10 text-hud-400",
};

export default async function ContabilidadCanalesPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const range = parseAnalyticsRange((await searchParams).range);

  try {
    const report = await api.analytics.salesByChannel(range);
    const total = report.by_channel.reduce((sum, c) => sum + c.revenue, 0);

    return (
      <div>
        <PageHeader
          title="Canales"
          description="Cuánto vende el agente por llamada telefónica, por chat web o por WhatsApp -- de dónde entra la plata."
        />
        <RangePicker basePath="/contabilidad/canales" active={range} />

        {report.by_channel.length === 0 ? (
          <p className="text-sm text-slate-500">Sin pedidos en este período.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {report.by_channel.map((c) => {
              const Icon = CHANNEL_ICON[c.key] ?? Hand;
              const accentClasses = CHANNEL_ACCENT[c.key] ?? CHANNEL_ACCENT.manual ?? "border-hud-400/35 bg-hud-500/10 text-hud-400";
              const barClass = accentClasses.split(" ").find((p) => p.startsWith("text-"))?.replace("text-", "bg-") ?? "bg-hud-400";
              const share = total > 0 ? c.revenue / total : 0;
              const avgTicket = c.orders > 0 ? c.revenue / c.orders : 0;
              return (
                <HudPanel key={c.key} className="p-5">
                  <div className="flex items-center justify-between">
                    <div className={`flex h-9 w-9 items-center justify-center border ${accentClasses}`}>
                      <Icon size={16} />
                    </div>
                    <span className="font-mono text-xs text-slate-500">{formatPercent(share)}</span>
                  </div>
                  <p className="mt-4 text-sm font-medium text-slate-200">{channelLabel(c.key)}</p>
                  <p className="mt-1 font-mono text-2xl font-semibold text-white">{formatCurrency(c.revenue)}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {c.orders} pedido{c.orders === 1 ? "" : "s"} · ticket prom. {formatCurrency(avgTicket)}
                  </p>
                  <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-surface-800">
                    <div className={`h-full rounded-full ${barClass}`} style={{ width: `${Math.max(2, share * 100)}%` }} />
                  </div>
                </HudPanel>
              );
            })}
          </div>
        )}

        <p className="mt-6 text-xs text-slate-500">
          "Manual" son pedidos sin conversación asociada (armados a mano desde el panel, o de antes de que existiera
          este seguimiento) -- no representan ventas del agente de voz/chat.
        </p>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Canales" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
