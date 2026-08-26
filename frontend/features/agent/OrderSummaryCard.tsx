import { ReceiptText } from "lucide-react";
import { OrderStatusBadge } from "@/components/Badge";
import { formatCurrency } from "@/lib/format";
import type { OrderOut } from "@/lib/types";

export function OrderSummaryCard({ order }: { order: OrderOut }) {
  return (
    <div className="rounded-xl border border-accent-teal/30 bg-accent-teal/5 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ReceiptText size={16} className="text-accent-teal" />
          <p className="text-sm font-semibold text-slate-100">Pedido #{order.id}</p>
        </div>
        <OrderStatusBadge status={order.status} />
      </div>
      <ul className="mt-3 space-y-1.5 text-sm text-slate-300">
        {order.items.map((item, idx) => (
          <li key={idx} className="flex justify-between gap-2">
            <span className="truncate">
              {item.quantity}× {item.product_name}
              {item.notes && <span className="text-slate-500"> ({item.notes})</span>}
            </span>
            <span className="shrink-0 text-slate-400">{formatCurrency(item.unit_price * item.quantity)}</span>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex items-center justify-between border-t border-accent-teal/20 pt-3 text-sm">
        <span className="text-slate-400">
          {order.requested_time ? `Entrega ${order.requested_time}` : "Sin hora definida"}
        </span>
        <span className="font-semibold text-white">{formatCurrency(order.total)}</span>
      </div>
    </div>
  );
}
