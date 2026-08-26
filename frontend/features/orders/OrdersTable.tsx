import { ClipboardList } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { OrderStatusBadge } from "@/components/Badge";
import { formatCurrency } from "@/lib/format";
import type { OrderOut } from "@/lib/types";

export function OrdersTable({ orders }: { orders: OrderOut[] }) {
  if (orders.length === 0) {
    return (
      <EmptyState
        icon={ClipboardList}
        title="Todavía no hay pedidos"
        description="Los pedidos aparecen aquí en cuanto el agente confirma uno en la pestaña Agente."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-surface-700 bg-surface-900">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-surface-700 text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-3 font-medium">Pedido</th>
              <th className="px-4 py-3 font-medium">Cliente</th>
              <th className="px-4 py-3 font-medium">Items</th>
              <th className="px-4 py-3 font-medium">Entrega</th>
              <th className="px-4 py-3 font-medium">Estado</th>
              <th className="px-4 py-3 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-800">
            {orders.map((order) => (
              <tr key={order.id} className="transition-colors hover:bg-surface-800/60">
                <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-200">#{order.id}</td>
                <td className="px-4 py-3 text-slate-300">
                  {order.customer_name ?? <span className="text-slate-500">Sin registrar</span>}
                </td>
                <td className="px-4 py-3 text-slate-400">
                  <ul className="space-y-0.5">
                    {order.items.map((item, idx) => (
                      <li key={idx} className="truncate">
                        <span className="text-slate-300">{item.quantity}×</span> {item.product_name}
                        {item.notes && <span className="text-slate-500"> · {item.notes}</span>}
                      </li>
                    ))}
                  </ul>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-400">
                  {order.requested_time ?? <span className="text-slate-600">—</span>}
                </td>
                <td className="whitespace-nowrap px-4 py-3">
                  <OrderStatusBadge status={order.status} />
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right font-medium text-slate-200">
                  {formatCurrency(order.total)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
