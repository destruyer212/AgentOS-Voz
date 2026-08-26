import { CircleDollarSign, ClipboardList, TriangleAlert, Users } from "lucide-react";
import Link from "next/link";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { ActivityFeed } from "@/features/audit/ActivityFeed";
import { RecentOrdersList } from "@/features/orders/RecentOrdersList";
import { ApiError, api } from "@/lib/api";
import { formatCurrency } from "@/lib/format";

export default async function DashboardPage() {
  try {
    const [orders, products, customers, logs] = await Promise.all([
      api.orders.list(100),
      api.products.list(),
      api.customers.list(),
      api.system.auditLogs(8),
    ]);

    const revenue = orders.reduce((sum, order) => sum + order.total, 0);
    const lowStock = products.filter((p) => p.stock_available <= 10).length;

    return (
      <div>
        <PageHeader
          title="Dashboard"
          description="Vista general del negocio conectado al agente."
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Pedidos" value={String(orders.length)} icon={ClipboardList} accent="brand" />
          <StatCard label="Ingresos" value={formatCurrency(revenue)} icon={CircleDollarSign} accent="teal" />
          <StatCard label="Clientes" value={String(customers.length)} icon={Users} accent="amber" />
          <StatCard
            label="Stock bajo"
            value={String(lowStock)}
            hint={`de ${products.length} productos`}
            icon={TriangleAlert}
            accent="rose"
          />
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-300">Pedidos recientes</h2>
              <Link href="/pedidos" className="text-xs font-medium text-brand-400 hover:text-brand-300">
                Ver todos →
              </Link>
            </div>
            <RecentOrdersList orders={orders.slice(0, 6)} />
          </div>

          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-300">Actividad reciente</h2>
              <Link href="/auditoria" className="text-xs font-medium text-brand-400 hover:text-brand-300">
                Ver todo →
              </Link>
            </div>
            <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
              <ActivityFeed logs={logs} />
            </div>
          </div>
        </div>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Dashboard" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
