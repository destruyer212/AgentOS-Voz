import { formatCurrency } from "@/lib/format";
import type { RevenueByDay } from "@/lib/types";

function formatDay(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("es-PE", { day: "2-digit", month: "short" });
}

// Grafico de barras verticales para la tendencia diaria de ingresos --
// sin libreria de graficos, solo divs con altura en % (el contenedor mide
// 160px fijo asi que el % de cada barra resuelve bien) y un tooltip nativo
// al pasar el mouse.
export function DailyTrendChart({ data }: { data: RevenueByDay[] }) {
  if (data.length === 0) {
    return <p className="text-sm text-slate-500">Sin pedidos en este período.</p>;
  }
  const max = Math.max(1, ...data.map((d) => d.revenue));

  return (
    <div className="flex h-40 gap-1">
      {data.map((d) => (
        <div key={d.date} className="group relative h-full min-w-0 flex-1">
          <div
            className="absolute bottom-0 left-0 w-full rounded-t bg-hud-400/70 transition-colors group-hover:bg-hud-300"
            style={{ height: `${Math.max(2, (d.revenue / max) * 100)}%` }}
          />
          <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-surface-700 bg-surface-900 px-2 py-1 text-xs text-slate-200 opacity-0 shadow-panel transition-opacity group-hover:opacity-100">
            {formatDay(d.date)}: {formatCurrency(d.revenue)} · {d.orders} pedido{d.orders === 1 ? "" : "s"}
          </div>
        </div>
      ))}
    </div>
  );
}
