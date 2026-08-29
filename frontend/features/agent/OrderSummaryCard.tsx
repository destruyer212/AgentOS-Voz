import { Bike, MapPin, ReceiptText, Store, Wallet } from "lucide-react";
import { OrderStatusBadge } from "@/components/Badge";
import { formatCurrency, fulfillmentLabel, paymentMethodLabel } from "@/lib/format";
import type { OrderOut } from "@/lib/types";

export function OrderSummaryCard({ order }: { order: OrderOut }) {
  const hasFulfillmentInfo = order.fulfillment_type || order.payment_method;

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

      {hasFulfillmentInfo && (
        <div className="mt-3 space-y-2 border-t border-accent-teal/20 pt-3 text-sm">
          {order.fulfillment_type && (
            <div className="flex items-start gap-2 text-slate-300">
              {order.fulfillment_type === "delivery" ? (
                <Bike size={15} className="mt-0.5 shrink-0 text-accent-teal" />
              ) : (
                <Store size={15} className="mt-0.5 shrink-0 text-accent-teal" />
              )}
              <span>{fulfillmentLabel(order.fulfillment_type)}</span>
            </div>
          )}
          {order.delivery_address && (
            <div className="flex items-start gap-2 text-slate-400">
              <MapPin size={15} className="mt-0.5 shrink-0 text-accent-teal" />
              <span className="leading-snug">{order.delivery_address}</span>
            </div>
          )}
          {order.payment_method && (
            <div className="flex items-start gap-2 text-slate-300">
              <Wallet size={15} className="mt-0.5 shrink-0 text-accent-teal" />
              <span>{paymentMethodLabel(order.payment_method)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
