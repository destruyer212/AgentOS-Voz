"use client";

import { Bike, ClipboardList, PhoneCall, Store, Wallet } from "lucide-react";
import Link from "next/link";
import { OrderStatusBadge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { formatCurrency, fulfillmentLabel, paymentMethodLabel } from "@/lib/format";
import type { OrderOut, OrderStatus } from "@/lib/types";
import { OrderStatusForm } from "./OrderStatusForm";

export interface BoardColumn {
  key: string;
  title: string;
  statuses: OrderStatus[];
}

// Tablero tipo Kanban compartido por /cocina y /recepcion: cada columna es
// un tramo del flujo real del pedido (ver _ORDER_STATUS_TRANSITIONS en
// services.py), no una lista libre -- asi cada pantalla solo ve lo que le
// toca hacer. La tabla de /pedidos (admin) no usa esto, sigue siendo la
// vista completa de siempre.
export function OrderBoard({
  orders,
  columns,
  emptyTitle,
  emptyDescription,
}: {
  orders: OrderOut[];
  columns: BoardColumn[];
  emptyTitle: string;
  emptyDescription: string;
}) {
  if (orders.length === 0) {
    return <EmptyState icon={ClipboardList} title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <div
      className="grid gap-5"
      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}
    >
      {columns.map((column) => {
        // El id es autoincremental -- sin un created_at propio en OrderOut,
        // es la mejor señal de orden que tenemos. Mas nuevo primero (bug
        // real, visto en vivo: con el mas viejo primero, un pedido recien
        // confirmado aparecia hasta el fondo de una lista larga y el
        // cocinero no lo veia sin bajar todo el scroll).
        const columnOrders = orders
          .filter((o) => column.statuses.includes(o.status as OrderStatus))
          .sort((a, b) => b.id - a.id);

        return (
          <section key={column.key} className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">{column.title}</h2>
              <span className="rounded-full bg-surface-800 px-2 py-0.5 font-mono text-xs text-slate-400">
                {columnOrders.length}
              </span>
            </div>

            {columnOrders.length === 0 ? (
              <p className="rounded-xl border border-dashed border-surface-700 px-4 py-6 text-center text-xs text-slate-500">
                Nada por aquí ahora mismo.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                {columnOrders.map((order) => (
                  <OrderCard key={order.id} order={order} />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

function OrderCard({ order }: { order: OrderOut }) {
  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-white">
            #{order.id} · {order.customer_name ?? <span className="text-slate-500">Sin registrar</span>}
          </p>
          <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-400">
            {order.fulfillment_type === "delivery" ? (
              <Bike size={13} className="shrink-0 text-hud-400" />
            ) : (
              <Store size={13} className="shrink-0 text-hud-400" />
            )}
            <span className="truncate">
              {order.fulfillment_type ? fulfillmentLabel(order.fulfillment_type) : "—"}
              {order.delivery_address && ` · ${order.delivery_address}`}
            </span>
          </div>
        </div>
        <OrderStatusBadge status={order.status} />
      </div>

      <ul className="mt-3 space-y-1 border-t border-surface-800 pt-3">
        {order.items.map((item, idx) => (
          <li key={idx} className="text-sm text-slate-300">
            <span className="font-medium text-white">{item.quantity}×</span> {item.product_name}
            {item.notes && <span className="text-slate-500"> · {item.notes}</span>}
          </li>
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
        {order.payment_method && (
          <span className="flex items-center gap-1">
            <Wallet size={12} className="text-hud-400" /> {paymentMethodLabel(order.payment_method)}
          </span>
        )}
        {order.requested_time && <span>Hora pedida: {order.requested_time}</span>}
        <span className="ml-auto font-mono text-sm font-medium text-slate-200">
          {formatCurrency(order.total)}
        </span>
      </div>

      {order.conversation_id && (
        <Link
          href={`/llamadas/${encodeURIComponent(order.conversation_id)}`}
          className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-hud-400 hover:underline"
        >
          <PhoneCall size={12} /> Ver conversación
        </Link>
      )}

      <div className="mt-4">
        <OrderStatusForm order={order} size="lg" />
      </div>
    </div>
  );
}
