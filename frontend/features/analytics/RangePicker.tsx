import Link from "next/link";
import type { AnalyticsRange } from "@/lib/types";

const RANGES: { key: AnalyticsRange; label: string }[] = [
  { key: "today", label: "Hoy" },
  { key: "7d", label: "7 días" },
  { key: "30d", label: "30 días" },
  { key: "90d", label: "90 días" },
  { key: "all", label: "Todo" },
];

// Selector de período compartido por las 6 pantallas de /contabilidad.
// Server component puro (nada de useState): cambiar de período navega a
// `${basePath}?range=X`, que vuelve a correr el server component de la
// pagina con datos frescos -- mismo patron de "todo se lee del servidor"
// que el resto del panel, sin duplicar estado en el cliente.
export function RangePicker({ basePath, active }: { basePath: string; active: AnalyticsRange }) {
  return (
    <div className="mb-6 inline-flex rounded-lg border border-surface-700 bg-surface-900 p-1">
      {RANGES.map((r) => (
        <Link
          key={r.key}
          href={`${basePath}?range=${r.key}`}
          className={`rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${
            active === r.key ? "bg-brand-500 text-white" : "text-slate-400 hover:text-slate-200"
          }`}
        >
          {r.label}
        </Link>
      ))}
    </div>
  );
}

export function parseAnalyticsRange(value: string | undefined): AnalyticsRange {
  const allowed: AnalyticsRange[] = ["today", "7d", "30d", "90d", "all"];
  return allowed.includes(value as AnalyticsRange) ? (value as AnalyticsRange) : "30d";
}
