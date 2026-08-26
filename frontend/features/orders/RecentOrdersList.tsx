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
    <div className="divide-y divide-surface-800 rounded-xl border border-surface-700 bg-surface-900">
      {orders.map((order) => (
        <div key={order.id} className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-200">
              #{order.id} · {order.customer_name ?? "Sin registrar"}
            </p>
            <p className="truncate text-xs text-slate-500">
              {order.items.map((item) => `${item.quantity}× ${item.product_name}`).join(", ")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <OrderStatusBadge status={order.status} />
            <span className="w-16 text-right text-sm font-semibold text-slate-200">
              {formatCurrency(order.total)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
