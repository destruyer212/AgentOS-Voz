import { Users } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import type { CustomerOut } from "@/lib/types";

export function CustomersTable({ customers }: { customers: CustomerOut[] }) {
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
            <th className="px-4 py-3 font-medium">Nombre</th>
            <th className="px-4 py-3 font-medium">Teléfono</th>
            <th className="px-4 py-3 font-medium">Dirección</th>
            <th className="px-4 py-3 font-medium">Notas</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-800">
          {customers.map((customer) => (
            <tr key={customer.id} className="transition-colors hover:bg-surface-800/60">
              <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-200">{customer.name}</td>
              <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-400">
                {customer.phone ?? "—"}
              </td>
              <td className="px-4 py-3 text-slate-400">{customer.address ?? "—"}</td>
              <td className="px-4 py-3 text-slate-500">{customer.notes ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
