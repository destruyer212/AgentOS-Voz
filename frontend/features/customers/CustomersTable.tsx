"use client";

import { ChevronDown, ClipboardList, Pencil, Phone, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { Fragment, useActionState, useEffect, useRef, useState } from "react";
import {
  deleteCustomerAction,
  updateCustomerAction,
  type DeleteCustomerState,
  type UpdateCustomerState,
} from "@/app/clientes/actions";
import { OrderStatusBadge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { Modal } from "@/components/Modal";
import { formatCurrency, formatDateTime } from "@/lib/format";
import type { CustomerOut, OrderOut } from "@/lib/types";

export function CustomersTable({ customers, orders }: { customers: CustomerOut[]; orders: OrderOut[] }) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editing, setEditing] = useState<CustomerOut | null>(null);
  const [deleting, setDeleting] = useState<CustomerOut | null>(null);

  if (customers.length === 0) {
    return (
      <EmptyState
        icon={Users}
        title="Sin clientes todavía"
        description="Se crean automáticamente cuando el agente toma un pedido con nombre y teléfono, o los agregas aquí."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-surface-700 bg-surface-900">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-700 text-xs uppercase tracking-wide text-slate-500">
            <th className="w-8 px-4 py-3" />
            <th className="px-4 py-3 font-medium">Nombre</th>
            <th className="px-4 py-3 font-medium">Teléfono</th>
            <th className="px-4 py-3 font-medium">Dirección</th>
            <th className="px-4 py-3 font-medium">Pedidos</th>
            <th className="w-20 px-4 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-800">
          {customers.map((customer) => {
            const customerOrders = orders.filter((o) => o.customer_id === customer.id);
            const isOpen = expandedId === customer.id;
            return (
              <Fragment key={customer.id}>
                <tr
                  className="cursor-pointer transition-colors hover:bg-surface-800/60"
                  onClick={() => setExpandedId(isOpen ? null : customer.id)}
                >
                  <td className="px-4 py-3 text-slate-500">
                    <ChevronDown
                      size={15}
                      className={`transition-transform ${isOpen ? "rotate-180 text-hud-400" : ""}`}
                    />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-200">{customer.name}</td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-400">
                    {customer.phone ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-400">{customer.address ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-400">{customerOrders.length}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => setEditing(customer)}
                        aria-label={`Editar ${customer.name}`}
                        className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-surface-700 hover:text-hud-400"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        onClick={() => setDeleting(customer)}
                        aria-label={`Eliminar ${customer.name}`}
                        className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-surface-700 hover:text-accent-rose"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
                {isOpen && (
                  <tr className="bg-surface-950/60">
                    <td colSpan={6} className="px-4 py-4">
                      <CustomerDetail customer={customer} orders={customerOrders} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>

      {editing && <EditCustomerModal customer={editing} onClose={() => setEditing(null)} />}
      {deleting && <DeleteCustomerModal customer={deleting} onClose={() => setDeleting(null)} />}
    </div>
  );
}

function CustomerDetail({ customer, orders }: { customer: CustomerOut; orders: OrderOut[] }) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_2fr]">
      <div className="space-y-1.5 text-xs">
        <p className="mb-2 font-medium uppercase tracking-wide text-slate-500">Notas</p>
        <p className="text-slate-300">{customer.notes || "Sin notas."}</p>
      </div>
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
          Historial de pedidos
        </p>
        {orders.length === 0 ? (
          <p className="text-sm text-slate-500">Este cliente todavía no tiene pedidos.</p>
        ) : (
          <ul className="space-y-2">
            {orders.map((order) => (
              <li
                key={order.id}
                className="flex flex-wrap items-center gap-3 rounded-lg border border-surface-700 bg-surface-900 px-3 py-2 text-xs"
              >
                <span className="font-mono text-slate-500">#{order.id}</span>
                <OrderStatusBadge status={order.status} />
                <span className="text-slate-400">{order.items.length} item(s)</span>
                <span className="font-medium text-slate-200">{formatCurrency(order.total)}</span>
                {order.conversation_id && (
                  <Link
                    href={`/llamadas/${encodeURIComponent(order.conversation_id)}`}
                    className="ml-auto inline-flex items-center gap-1 text-hud-400 hover:text-hud-300"
                  >
                    <Phone size={12} /> Ver conversación
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

const initialUpdateState: UpdateCustomerState = {};

function EditCustomerModal({ customer, onClose }: { customer: CustomerOut; onClose: () => void }) {
  const [state, formAction, isPending] = useActionState(updateCustomerAction, initialUpdateState);

  useEffect(() => {
    if (state.success) onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.success]);

  return (
    <Modal title={`Editar ${customer.name}`} onClose={onClose}>
      <form action={formAction} className="space-y-3">
        <input type="hidden" name="id" value={customer.id} />
        <input name="name" defaultValue={customer.name} placeholder="Nombre *" required className="form-input" />
        <input name="phone" defaultValue={customer.phone ?? ""} placeholder="Teléfono" className="form-input" />
        <input
          name="address"
          defaultValue={customer.address ?? ""}
          placeholder="Dirección"
          className="form-input"
        />
        <input name="notes" defaultValue={customer.notes ?? ""} placeholder="Notas" className="form-input" />
        {state.error && <p className="text-sm text-accent-rose">{state.error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancelar
          </button>
          <button type="submit" disabled={isPending} className="btn-primary">
            {isPending ? "Guardando…" : "Guardar cambios"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const initialDeleteState: DeleteCustomerState = {};

function DeleteCustomerModal({ customer, onClose }: { customer: CustomerOut; onClose: () => void }) {
  const [state, formAction, isPending] = useActionState(deleteCustomerAction, initialDeleteState);
  const closedRef = useRef(false);

  useEffect(() => {
    if (state.success && !closedRef.current) {
      closedRef.current = true;
      onClose();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.success]);

  return (
    <Modal title="Eliminar cliente" onClose={onClose}>
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg border border-accent-rose/30 bg-accent-rose/5 p-3">
          <ClipboardList size={16} className="mt-0.5 shrink-0 text-accent-rose" />
          <p className="text-sm text-slate-300">
            ¿Eliminar a <span className="font-medium text-white">{customer.name}</span>? Esta acción no se
            puede deshacer. Si tiene pedidos o conversaciones registradas, no se podrá eliminar.
          </p>
        </div>
        {state.error && <p className="text-sm text-accent-rose">{state.error}</p>}
        <form action={formAction} className="flex justify-end gap-2">
          <input type="hidden" name="id" value={customer.id} />
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancelar
          </button>
          <button
            type="submit"
            disabled={isPending}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent-rose px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-rose/80 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPending ? "Eliminando…" : "Sí, eliminar"}
          </button>
        </form>
      </div>
    </Modal>
  );
}
