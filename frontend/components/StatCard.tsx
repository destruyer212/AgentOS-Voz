import type { ComponentType } from "react";
import { HudPanel } from "./HudPanel";

interface StatCardProps {
  label: string;
  value: string;
  hint?: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  accent?: "brand" | "teal" | "amber" | "rose" | "hud";
}

const ACCENT_CLASSES: Record<NonNullable<StatCardProps["accent"]>, string> = {
  brand: "border-brand-400/35 bg-brand-500/10 text-brand-400",
  teal: "border-accent-teal/35 bg-accent-teal/10 text-accent-teal",
  amber: "border-accent-amber/35 bg-accent-amber/10 text-accent-amber",
  rose: "border-accent-rose/35 bg-accent-rose/10 text-accent-rose",
  hud: "border-hud-400/35 bg-hud-500/10 text-hud-400",
};

export function StatCard({ label, value, hint, icon: Icon, accent = "brand" }: StatCardProps) {
  return (
    <HudPanel className="min-h-[150px] p-5">
      <div className="flex items-start justify-between">
        <p className="font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-slate-500">{label}</p>
        <div className={`flex h-9 w-9 items-center justify-center border ${ACCENT_CLASSES[accent]}`}>
          <Icon size={16} />
        </div>
      </div>
      <p className="mt-4 font-mono text-3xl font-semibold text-white">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      <div className="mt-4 flex h-5 items-end gap-1">
        {[35, 42, 38, 63, 44, 41, 50, 66].map((height, index) => (
          <span
            key={index}
            className={`w-full bg-current ${ACCENT_CLASSES[accent]
              .split(" ")
              .find((part) => part.startsWith("text-"))}`}
            style={{ height: `${height}%`, opacity: index % 3 === 0 ? 0.7 : 0.35 }}
          />
        ))}
      </div>
    </HudPanel>
  );
}
