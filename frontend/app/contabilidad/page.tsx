import { CircleDollarSign, ClipboardList, TicketPercent, XCircle } from "lucide-react";
import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { HudPanel } from "@/components/HudPanel";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { BarList } from "@/features/analytics/BarList";
import { DailyTrendChart } from "@/features/analytics/DailyTrendChart";
import { parseAnalyticsRange, RangePicker } from "@/features/analytics/RangePicker";
import { ApiError, api } from "@/lib/api";
import { formatCurrency, formatPercent, fulfillmentLabel, paymentMethodLabel } from "@/lib/format";

export const metadata: Metadata = { title: "Contabilidad" };

export default async function ContabilidadPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const range = parseAnalyticsRange((await searchParams).range);

  try {
    const summary = await api.analytics.summary(range);

    return (
      <div>
        <PageHeader
          title="Contabilidad"
          description="Ingresos reales del negocio -- calculados sobre los pedidos confirmados, sin contar cancelados."
        />
        <RangePicker basePath="/contabilidad" active={range} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Ingresos" value={formatCurrency(summary.revenue_total)} icon={CircleDollarSign} accent="teal" />
          <StatCard label="Pedidos" value={String(summary.orders_count)} icon={ClipboardList} accent="hud" />
          <StatCard label="Ticket promedio" value={formatCurrency(summary.average_ticket)} icon={TicketPercent} accent="brand" />
          <StatCard
            label="Cancelados"
            value={String(summary.cancelled_count)}
            hint={`${formatPercent(summary.cancelled_rate)} de los pedidos`}
            icon={XCircle}
            accent="rose"
          />
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.4fr_1fr]">
          <HudPanel className="p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-200">Ingresos por día</h2>
            <DailyTrendChart data={summary.revenue_by_day} />
          </HudPanel>

          <div className="space-y-6">
            <HudPanel className="p-5">
              <h2 className="mb-4 text-sm font-semibold text-slate-200">Por tipo de entrega</h2>
              <BarList
                rows={summary.revenue_by_fulfillment.map((r) => ({
                  label: fulfillmentLabel(r.key),
                  value: r.revenue,
                  secondary: `${r.orders} pedido${r.orders === 1 ? "" : "s"}`,
                }))}
                formatValue={formatCurrency}
                accent="teal"
              />
            </HudPanel>
            <HudPanel className="p-5">
              <h2 className="mb-4 text-sm font-semibold text-slate-200">Por método de pago</h2>
              <BarList
                rows={summary.revenue_by_payment_method.map((r) => ({
                  label: paymentMethodLabel(r.key),
                  value: r.revenue,
                  secondary: `${r.orders} pedido${r.orders === 1 ? "" : "s"}`,
                }))}
                formatValue={formatCurrency}
                accent="amber"
              />
            </HudPanel>
          </div>
        </div>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Contabilidad" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
