import { MessageSquare, Phone } from "lucide-react";
import { orderStatusLabel } from "@/lib/format";
import type { OrderStatus } from "@/lib/types";

const STATUS_STYLES: Record<OrderStatus, string> = {
  draft: "bg-surface-700 text-slate-300",
  pending_confirmation: "bg-accent-amber/15 text-accent-amber",
  confirmed: "bg-accent-teal/15 text-accent-teal",
  preparing: "bg-brand-500/15 text-brand-400",
  ready: "bg-brand-500/15 text-brand-400",
  scheduled: "bg-accent-teal/15 text-accent-teal",
  delivered: "bg-emerald-500/15 text-emerald-400",
  cancelled: "bg-surface-700 text-slate-400",
  failed: "bg-accent-rose/15 text-accent-rose",
};

export function OrderStatusBadge({ status }: { status: string }) {
  const className = STATUS_STYLES[status as OrderStatus] ?? "bg-surface-700 text-slate-300";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${className}`}>
      {orderStatusLabel(status)}
    </span>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "success" | "danger" | "info";
}) {
  const toneClass = {
    neutral: "bg-surface-700 text-slate-300",
    success: "bg-accent-teal/15 text-accent-teal",
    danger: "bg-accent-rose/15 text-accent-rose",
    info: "bg-brand-500/15 text-brand-400",
  }[tone];

  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${toneClass}`}>
      {children}
    </span>
  );
}

export function ChannelBadge({ channel }: { channel: string }) {
  const isPhone = channel === "phone";
  const Icon = isPhone ? Phone : MessageSquare;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        isPhone ? "bg-accent-amber/15 text-accent-amber" : "bg-brand-500/15 text-brand-400"
      }`}
    >
      <Icon size={12} />
      {isPhone ? "Llamada" : "Chat web"}
    </span>
  );
}
