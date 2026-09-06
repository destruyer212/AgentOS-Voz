import { Crown, Repeat } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { HudPanel } from "@/components/HudPanel";
import { PageHeader } from "@/components/PageHeader";
import { parseAnalyticsRange, RangePicker } from "@/features/analytics/RangePicker";
import { ApiError, api } from "@/lib/api";
import { formatCurrency, formatDateTime } from "@/lib/format";
import type { TopCustomerRow } from "@/lib/types";

export const metadata: Metadata = { title: "Contabilidad · Clientes" };

function CustomerRankTable({ rows, valueLabel, formatMain }: { rows: TopCustomerRow[]; valueLabel: string; formatMain: (row: TopCustomerRow) => string }) {
  if (rows.length === 0) return <p className="text-sm text-slate-500">Sin clientes registrados con pedidos en este período.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-700 text-xs uppercase tracking-wide text-slate-500">
            <th className="py-2 pr-3 font-medium">#</th>
            <th className="py-2 pr-3 font-medium">Cliente</th>
            <th className="py-2 pr-3 font-medium">Teléfono</th>
            <th className="py-2 pr-3 text-right font-medium">Pedidos</th>
            <th className="py-2 pr-3 text-right font-medium">Ticket prom.</th>
            <th className="py-2 pr-3 font-medium">Último pedido</th>
            <th className="py-2 text-right font-medium">{valueLabel}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-800">
          {rows.map((row, idx) => (
            <tr key={row.customer_id}>
              <td className="py-2 pr-3 font-mono text-xs text-slate-500">{idx + 1}</td>
              <td className="py-2 pr-3 text-slate-200">
                <Link href={`/clientes?q=${encodeURIComponent(row.name)}`} className="hover:text-hud-400 hover:underline">
                  {row.name}
                </Link>
              </td>
              <td className="py-2 pr-3 text-slate-400">{row.phone ?? "—"}</td>
              <td className="py-2 pr-3 text-right text-slate-400">{row.orders_count}</td>
              <td className="py-2 pr-3 text-right text-slate-400">{formatCurrency(row.average_ticket)}</td>
              <td className="py-2 pr-3 text-slate-500">{formatDateTime(row.last_order_at)}</td>
              <td className="py-2 text-right font-medium text-slate-200">{formatMain(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function ContabilidadClientesPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const range = parseAnalyticsRange((await searchParams).range);

  try {
    const report = await api.analytics.topCustomers(range, 15);

    return (
      <div>
        <PageHeader title="Clientes" description="Quién gasta más y quién pide más seguido -- no siempre coincide." />
        <RangePicker basePath="/contabilidad/clientes" active={range} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <HudPanel className="p-4">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">Clientes registrados</p>
            <p className="mt-2 font-mono text-2xl font-semibold text-white">{report.registered_customers}</p>
          </HudPanel>
          <HudPanel className="p-4">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">Pedidos sin cliente registrado</p>
            <p className="mt-2 font-mono text-2xl font-semibold text-white">{report.anonymous_orders}</p>
          </HudPanel>
          <HudPanel className="p-4">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">Ingresos sin registrar</p>
            <p className="mt-2 font-mono text-2xl font-semibold text-white">{formatCurrency(report.anonymous_revenue)}</p>
          </HudPanel>
        </div>

        <HudPanel className="mt-6 p-5">
          <div className="mb-4 flex items-center gap-2">
            <Crown size={16} className="text-accent-amber" />
            <h2 className="text-sm font-semibold text-slate-200">Los que más gastan</h2>
          </div>
          <CustomerRankTable rows={report.by_spend} valueLabel="Gastado" formatMain={(r) => formatCurrency(r.revenue)} />
        </HudPanel>

        <HudPanel className="mt-6 p-5">
          <div className="mb-4 flex items-center gap-2">
            <Repeat size={16} className="text-brand-400" />
            <h2 className="text-sm font-semibold text-slate-200">Los más frecuentes</h2>
          </div>
          <CustomerRankTable rows={report.by_frequency} valueLabel="Gastado" formatMain={(r) => `${r.orders_count} pedidos`} />
        </HudPanel>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Clientes" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
