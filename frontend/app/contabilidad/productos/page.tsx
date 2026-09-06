import { Flame, Soup, UtensilsCrossed } from "lucide-react";
import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { HudPanel } from "@/components/HudPanel";
import { PageHeader } from "@/components/PageHeader";
import { BarList } from "@/features/analytics/BarList";
import { parseAnalyticsRange, RangePicker } from "@/features/analytics/RangePicker";
import { ApiError, api } from "@/lib/api";
import { categoryLabel, formatCurrency } from "@/lib/format";
import type { TopProductRow } from "@/lib/types";

export const metadata: Metadata = { title: "Contabilidad · Productos" };

function ProductRankTable({ rows, valueLabel, formatMain }: { rows: TopProductRow[]; valueLabel: string; formatMain: (row: TopProductRow) => string }) {
  if (rows.length === 0) return <p className="text-sm text-slate-500">Sin ventas en este período.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-700 text-xs uppercase tracking-wide text-slate-500">
            <th className="py-2 pr-3 font-medium">#</th>
            <th className="py-2 pr-3 font-medium">Plato</th>
            <th className="py-2 pr-3 font-medium">Categoría</th>
            <th className="py-2 pr-3 text-right font-medium">Pedidos</th>
            <th className="py-2 text-right font-medium">{valueLabel}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-800">
          {rows.map((row, idx) => (
            <tr key={row.product_id}>
              <td className="py-2 pr-3 font-mono text-xs text-slate-500">{idx + 1}</td>
              <td className="py-2 pr-3 text-slate-200">{row.name}</td>
              <td className="py-2 pr-3 text-slate-400">{categoryLabel(row.category)}</td>
              <td className="py-2 pr-3 text-right text-slate-400">{row.orders_count}</td>
              <td className="py-2 text-right font-medium text-slate-200">{formatMain(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function ContabilidadProductosPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const range = parseAnalyticsRange((await searchParams).range);

  try {
    const report = await api.analytics.topProducts(range, 15);

    return (
      <div>
        <PageHeader
          title="Productos"
          description="Qué platos se piden más y cuáles dejan más plata -- no siempre son los mismos."
        />
        <RangePicker basePath="/contabilidad/productos" active={range} />

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <HudPanel className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <Flame size={16} className="text-accent-amber" />
              <h2 className="text-sm font-semibold text-slate-200">Más pedidos (por cantidad)</h2>
            </div>
            <ProductRankTable rows={report.by_quantity} valueLabel="Cantidad" formatMain={(r) => `${r.quantity}×`} />
          </HudPanel>

          <HudPanel className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <UtensilsCrossed size={16} className="text-accent-teal" />
              <h2 className="text-sm font-semibold text-slate-200">Los que más ingresos dejan</h2>
            </div>
            <ProductRankTable rows={report.by_revenue} valueLabel="Ingreso" formatMain={(r) => formatCurrency(r.revenue)} />
          </HudPanel>
        </div>

        <HudPanel className="mt-6 p-5">
          <div className="mb-4 flex items-center gap-2">
            <Soup size={16} className="text-brand-400" />
            <h2 className="text-sm font-semibold text-slate-200">Por categoría</h2>
          </div>
          <BarList
            rows={report.by_category.map((c) => ({
              label: categoryLabel(c.category),
              value: c.revenue,
              secondary: `${c.quantity} unidades`,
            }))}
            formatValue={formatCurrency}
            accent="brand"
          />
        </HudPanel>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Productos" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
