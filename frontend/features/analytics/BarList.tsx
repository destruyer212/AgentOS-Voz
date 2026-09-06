interface BarListRow {
  label: string;
  value: number;
  secondary?: string;
}

const ACCENT_BAR: Record<"brand" | "teal" | "amber" | "rose" | "hud", string> = {
  brand: "bg-brand-500",
  teal: "bg-accent-teal",
  amber: "bg-accent-amber",
  rose: "bg-accent-rose",
  hud: "bg-hud-400",
};

// Lista de barras horizontales -- usada en toda /contabilidad para
// desgloses (metodo de pago, canal, categoria, dia de la semana...) sin
// meter una libreria de graficos para algo que un par de divs resuelve.
export function BarList({
  rows,
  formatValue = (v) => String(v),
  accent = "brand",
}: {
  rows: BarListRow[];
  formatValue?: (value: number) => string;
  accent?: keyof typeof ACCENT_BAR;
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">Sin datos en este período.</p>;
  }
  const max = Math.max(1, ...rows.map((r) => r.value));

  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="mb-1 flex items-center justify-between gap-3 text-sm">
            <span className="truncate text-slate-300">{row.label}</span>
            <span className="shrink-0 font-mono text-xs text-slate-400">
              {formatValue(row.value)}
              {row.secondary ? ` · ${row.secondary}` : ""}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-surface-800">
            <div
              className={`h-full rounded-full ${ACCENT_BAR[accent]}`}
              style={{ width: `${Math.max(2, (row.value / max) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
