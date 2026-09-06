import { CalendarClock, Clock } from "lucide-react";
import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { HudPanel } from "@/components/HudPanel";
import { PageHeader } from "@/components/PageHeader";
import { BarList } from "@/features/analytics/BarList";
import { parseAnalyticsRange, RangePicker } from "@/features/analytics/RangePicker";
import { ApiError, api } from "@/lib/api";
import { formatCurrency } from "@/lib/format";

export const metadata: Metadata = { title: "Contabilidad · Horarios" };

export default async function ContabilidadHorariosPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const range = parseAnalyticsRange((await searchParams).range);

  try {
    const report = await api.analytics.salesByTime(range);

    return (
      <div>
        <PageHeader
          title="Horarios"
          description="Cuándo vende más el negocio -- útil para saber cuándo reforzar cocina o mostrador."
        />
        <RangePicker basePath="/contabilidad/horarios" active={range} />

        {(report.peak_weekday || report.peak_hour) && (
          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
            {report.peak_weekday && (
              <HudPanel className="p-4">
                <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">Mejor día</p>
                <p className="mt-2 text-lg font-semibold text-white">{report.peak_weekday.label}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {formatCurrency(report.peak_weekday.revenue)} · {report.peak_weekday.orders} pedidos
                </p>
              </HudPanel>
            )}
            {report.peak_hour && (
              <HudPanel className="p-4">
                <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">Mejor hora</p>
                <p className="mt-2 text-lg font-semibold text-white">{report.peak_hour.label}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {formatCurrency(report.peak_hour.revenue)} · {report.peak_hour.orders} pedidos
                </p>
              </HudPanel>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <HudPanel className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <CalendarClock size={16} className="text-accent-teal" />
              <h2 className="text-sm font-semibold text-slate-200">Por día de la semana</h2>
            </div>
            <BarList
              rows={report.by_weekday.map((w) => ({
                label: w.label,
                value: w.revenue,
                secondary: `${w.orders} pedido${w.orders === 1 ? "" : "s"}`,
              }))}
              formatValue={formatCurrency}
              accent="teal"
            />
          </HudPanel>

          <HudPanel className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <Clock size={16} className="text-brand-400" />
              <h2 className="text-sm font-semibold text-slate-200">Por hora del día</h2>
            </div>
            <BarList
              rows={report.by_hour
                .filter((h) => h.orders > 0)
                .map((h) => ({
                  label: h.label,
                  value: h.revenue,
                  secondary: `${h.orders} pedido${h.orders === 1 ? "" : "s"}`,
                }))}
              formatValue={formatCurrency}
              accent="brand"
            />
          </HudPanel>
        </div>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Horarios" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
