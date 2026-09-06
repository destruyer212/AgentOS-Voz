"use client";

import { useActionState } from "react";
import { updateOrderStatusAction, type UpdateOrderStatusState } from "@/app/pedidos/actions";
import type { OrderOut, OrderStatus } from "@/lib/types";
import { TERMINAL_STATUSES, getNextActions, type NextAction } from "./orderActions";

const initialState: UpdateOrderStatusState = {};

// Compartido por /pedidos (admin), /cocina y /recepcion -- un solo lugar
// para el botoneo de "siguiente estado", asi las 3 pantallas nunca se
// desincronizan entre si. `size="lg"` es para las tarjetas grandes de
// cocina/recepcion (pensadas para tocar con el dedo desde una tablet en el
// mostrador, no para el mouse); el admin sigue usando el tamaño chico de
// siempre dentro de la tabla.
export function OrderStatusForm({ order, size = "sm" }: { order: OrderOut; size?: "sm" | "lg" }) {
  const actions = getNextActions(order);

  if (TERMINAL_STATUSES.includes(order.status as OrderStatus)) {
    return <p className="text-xs text-slate-500">Este pedido ya está cerrado, no admite más cambios.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {actions.map((action) => (
        <OrderStatusButton key={action.status} order={order} action={action} size={size} />
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
function OrderStatusButton({
  order,
  action,
  size,
}: {
  order: OrderOut;
  action: NextAction;
  size: "sm" | "lg";
}) {
  const [state, formAction, isPending] = useActionState(updateOrderStatusAction, initialState);
  const Icon = action.icon;
  const sizeClass = size === "lg" ? "!py-3.5 !text-base" : "";

  return (
    <form action={formAction}>
      <input type="hidden" name="id" value={order.id} />
      <input type="hidden" name="status" value={action.status} />
      <button
        type="submit"
        disabled={isPending}
        className={`${
          action.tone === "danger" ? "btn-secondary w-full text-accent-rose" : "btn-primary w-full"
        } ${sizeClass}`}
      >
        <Icon size={size === "lg" ? 18 : 14} />
        {isPending ? "Actualizando…" : action.label}
      </button>
      {state.error && <p className="mt-1 text-xs text-accent-rose">{state.error}</p>}
    </form>
  );
}
