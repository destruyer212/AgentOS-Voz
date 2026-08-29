import { ClipboardList } from "lucide-react";
import { OrderStatusBadge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { formatCurrency } from "@/lib/format";
import type { OrderOut } from "@/lib/types";

// Version compacta de OrdersTable para el widget del dashboard: la tabla
// completa (6 columnas) no entra en la columna lateral sin scroll
// horizontal feo, asi que aqui priorizamos # + cliente + total + estado.
export function RecentOrdersList({ orders }: { orders: OrderOut[] }) {
  if (orders.length === 0) {
    return (
      <EmptyState
        icon={ClipboardList}
        title="Todavía no hay pedidos"
        description="Aparecen aquí en cuanto el agente confirme uno en la pestaña Agente."
      />
    );
  }

  return (
    <div className="overflow-hidden border border-hud-500/20 bg-surface-900/65 shadow-panel backdrop-blur-md">
      <div className="grid grid-cols-[1fr_110px_96px] border-b border-surface-700/80 px-4 py-3 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">
        <span>Pedido</span>
        <span>Estado</span>
        <span className="text-right">Total</span>
      </div>
      {orders.map((order) => (
        <div
          key={order.id}
          className="grid grid-cols-[1fr_110px_96px] items-center gap-3 border-b border-surface-800/70 px-4 py-3 last:border-b-0 hover:bg-hud-500/[0.04]"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-200">
              #{order.id} · {order.customer_name ?? "Sin registrar"}
            </p>
            <p className="truncate text-xs text-slate-500">
              {order.items.map((item) => `${item.quantity}× ${item.product_name}`).join(", ")}
            </p>
          </div>
          <OrderStatusBadge status={order.status} />
          <span className="text-right font-mono text-sm font-semibold text-slate-200">{formatCurrency(order.total)}</span>
        </div>
      ))}
    </div>
  );
}
