import type { ComponentType } from "react";

interface StatCardProps {
  label: string;
  value: string;
  hint?: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  accent?: "brand" | "teal" | "amber" | "rose";
}

const ACCENT_CLASSES: Record<NonNullable<StatCardProps["accent"]>, string> = {
  brand: "bg-brand-500/15 text-brand-400",
  teal: "bg-accent-teal/15 text-accent-teal",
  amber: "bg-accent-amber/15 text-accent-amber",
  rose: "bg-accent-rose/15 text-accent-rose",
};

export function StatCard({ label, value, hint, icon: Icon, accent = "brand" }: StatCardProps) {
  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900 p-5 shadow-panel">
      <div className="flex items-start justify-between">
        <p className="text-sm text-slate-400">{label}</p>
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${ACCENT_CLASSES[accent]}`}>
          <Icon size={16} />
        </div>
      </div>
      <p className="mt-3 text-2xl font-semibold text-white">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
