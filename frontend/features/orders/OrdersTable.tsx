"use client";

import {
  Bike,
  CheckCircle2,
  ChefHat,
  ChevronDown,
  ClipboardList,
  PackageCheck,
  PhoneCall,
  Store,
  Wallet,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import type { ComponentType } from "react";
import { Fragment, useActionState, useState } from "react";
import { updateOrderStatusAction, type UpdateOrderStatusState } from "@/app/pedidos/actions";
import { OrderStatusBadge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { formatCurrency, fulfillmentLabel, paymentMethodLabel } from "@/lib/format";
import type { OrderOut, OrderStatus } from "@/lib/types";

// Un solo "siguiente paso" por estado (nunca un desplegable libre): asi
// cocina/mostrador no pueden saltarse pasos por accidente -- el backend
// tambien lo valida (ver _ORDER_STATUS_TRANSITIONS en services.py), esto
// solo evita mostrar botones que igual el servidor rechazaria. "dispatched"
// (sale con el motorizado) dispara el aviso de WhatsApp "ya salió, ~30
// min"; "ready" en recojo dispara el aviso de "ya está listo".
const TERMINAL_STATUSES: OrderStatus[] = ["delivered", "cancelled", "failed"];

interface NextAction {
  status: OrderStatus;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  tone: "primary" | "danger";
}

function getNextActions(order: OrderOut): NextAction[] {
  const cancel: NextAction = { status: "cancelled", label: "Cancelar pedido", icon: XCircle, tone: "danger" };
  const isDelivery = order.fulfillment_type === "delivery";

  switch (order.status as OrderStatus) {
    case "draft":
    case "pending_confirmation":
      return [{ status: "confirmed", label: "Confirmar pedido", icon: CheckCircle2, tone: "primary" }, cancel];
    case "confirmed":
    case "scheduled":
      return [{ status: "preparing", label: "Aceptar en cocina", icon: ChefHat, tone: "primary" }, cancel];
    case "preparing":
      return isDelivery
        ? [
            { status: "dispatched", label: "Salió con el motorizado", icon: Bike, tone: "primary" },
            cancel,
          ]
        : [
            { status: "ready", label: "Marcar listo para recoger", icon: PackageCheck, tone: "primary" },
            cancel,
          ];
    case "ready":
      return [
        { status: "delivered", label: "Cliente recogió su pedido", icon: CheckCircle2, tone: "primary" },
        cancel,
      ];
    case "dispatched":
      return [{ status: "delivered", label: "Motorizado entregó el pedido", icon: CheckCircle2, tone: "primary" }];
    default:
      return [];
  }
}

export function OrdersTable({ orders }: { orders: OrderOut[] }) {
  const [expandedId, setExpandedId] = useState<number | null>(null);

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
              <th className="w-8 px-4 py-3" />
              <th className="px-4 py-3 font-medium">Pedido</th>
              <th className="px-4 py-3 font-medium">Cliente</th>
              <th className="px-4 py-3 font-medium">Items</th>
              <th className="px-4 py-3 font-medium">Entrega y pago</th>
              <th className="px-4 py-3 font-medium">Estado</th>
              <th className="px-4 py-3 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-800">
            {orders.map((order) => {
              const isOpen = expandedId === order.id;
              return (
                <Fragment key={order.id}>
                  <tr
                    className="cursor-pointer transition-colors hover:bg-surface-800/60"
                    onClick={() => setExpandedId(isOpen ? null : order.id)}
                  >
                    <td className="px-4 py-3 text-slate-500">
                      <ChevronDown
                        size={15}
                        className={`transition-transform ${isOpen ? "rotate-180 text-hud-400" : ""}`}
                      />
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-200">#{order.id}</td>
                    <td className="px-4 py-3 text-slate-300">
                      {order.customer_name ?? <span className="text-slate-500">Sin registrar</span>}
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {order.items.length} item{order.items.length === 1 ? "" : "s"}
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {order.fulfillment_type ? (
                        <div className="flex items-center gap-1.5">
                          {order.fulfillment_type === "delivery" ? (
                            <Bike size={13} className="shrink-0 text-hud-400" />
                          ) : (
                            <Store size={13} className="shrink-0 text-hud-400" />
                          )}
                          <span className="text-slate-300">{fulfillmentLabel(order.fulfillment_type)}</span>
                        </div>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <OrderStatusBadge status={order.status} />
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-medium text-slate-200">
                      {formatCurrency(order.total)}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="bg-surface-950/60">
                      <td colSpan={7} className="px-4 py-4">
                        <OrderDetail order={order} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OrderDetail({ order }: { order: OrderOut }) {
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.2fr_1fr]">
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Items del pedido</p>
        <ul className="space-y-1.5">
          {order.items.map((item, idx) => (
            <li
              key={idx}
              className="flex items-center justify-between rounded-lg border border-surface-700 bg-surface-900 px-3 py-2 text-sm"
            >
              <span className="text-slate-300">
                <span className="font-medium text-white">{item.quantity}×</span> {item.product_name}
                {item.notes && <span className="text-slate-500"> · {item.notes}</span>}
              </span>
              <span className="font-mono text-xs text-slate-500">{formatCurrency(item.unit_price)}</span>
            </li>
          ))}
        </ul>

        <div className="mt-3 space-y-1 text-xs text-slate-400">
          {order.fulfillment_type && (
            <p>
              <span className="text-slate-500">Entrega:</span> {fulfillmentLabel(order.fulfillment_type)}
              {order.delivery_address && ` · ${order.delivery_address}`}
            </p>
          )}
          {order.payment_method && (
            <p className="flex items-center gap-1.5">
              <Wallet size={12} className="text-hud-400" /> {paymentMethodLabel(order.payment_method)}
            </p>
          )}
          {order.requested_time && (
            <p>
              <span className="text-slate-500">Hora pedida:</span> {order.requested_time}
            </p>
          )}
        </div>

        {order.conversation_id && (
          <Link
            href={`/llamadas/${encodeURIComponent(order.conversation_id)}`}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-hud-500/30 bg-hud-500/10 px-3 py-1.5 text-xs font-medium text-hud-400 transition-colors hover:bg-hud-500/20"
          >
            <PhoneCall size={13} /> Ver conversación completa
          </Link>
        )}
      </div>

      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Cambiar estado</p>
        <OrderStatusForm order={order} />
      </div>
    </div>
  );
}

const initialState: UpdateOrderStatusState = {};

function OrderStatusForm({ order }: { order: OrderOut }) {
  const actions = getNextActions(order);

  if (TERMINAL_STATUSES.includes(order.status as OrderStatus)) {
    return <p className="text-xs text-slate-500">Este pedido ya está cerrado, no admite más cambios.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {actions.map((action) => (
        <OrderStatusButton key={action.status} order={order} action={action} />
      ))}
    </div>
  );
}

// Bug real, visto en vivo: con varios botones "submit" (nombre/valor
// distinto cada uno) dentro de UN SOLO <form>, el estado que React arma al
// llamar a la Server Action no siempre incluye cual boton disparo el
// envio -- "status" llegaba vacio y el servidor respondia "Datos
// inválidos." sin importar cual boton se apretara. Cada boton con su
// propio <form> (y su propio useActionState) elimina esa ambiguedad por
// completo: el valor de "status" queda fijo en un input oculto, no
// depende de cual boton disparo el submit.
function OrderStatusButton({ order, action }: { order: OrderOut; action: NextAction }) {
  const [state, formAction, isPending] = useActionState(updateOrderStatusAction, initialState);
  const Icon = action.icon;

  return (
    <form action={formAction}>
      <input type="hidden" name="id" value={order.id} />
      <input type="hidden" name="status" value={action.status} />
      <button
        type="submit"
        disabled={isPending}
        className={
          action.tone === "danger" ? "btn-secondary w-full text-accent-rose" : "btn-primary w-full"
        }
      >
        <Icon size={14} />
        {isPending ? "Actualizando…" : action.label}
      </button>
      {state.error && <p className="mt-1 text-xs text-accent-rose">{state.error}</p>}
    </form>
  );
}
