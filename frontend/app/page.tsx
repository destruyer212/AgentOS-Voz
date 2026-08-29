import { CircleDollarSign, ClipboardList, TriangleAlert, Users } from "lucide-react";
import Link from "next/link";
import { AgentCore } from "@/components/AgentCore";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { DashboardHero } from "@/components/DashboardHero";
import { HudPanel } from "@/components/HudPanel";
import { StatCard } from "@/components/StatCard";
import { ActivityFeed } from "@/features/audit/ActivityFeed";
import { RecentOrdersList } from "@/features/orders/RecentOrdersList";
import { ApiError, api } from "@/lib/api";
import { formatCurrency } from "@/lib/format";

export default async function DashboardPage() {
  try {
    const [orders, products, customers, logs, businessInfo] = await Promise.all([
      api.orders.list(100),
      api.products.list(),
      api.customers.list(),
      api.system.auditLogs(8),
      api.system.businessInfo(),
    ]);

    const revenue = orders.reduce((sum, order) => sum + order.total, 0);
    const lowStock = products.filter((p) => p.stock_available <= 10).length;

    return (
      <div>
        <DashboardHero restaurantName={businessInfo.restaurant_name} />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_280px_minmax(0,1fr)]">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <StatCard label="Pedidos" value={String(orders.length)} icon={ClipboardList} accent="hud" />
            <StatCard label="Ingresos" value={formatCurrency(revenue)} icon={CircleDollarSign} accent="teal" />
          </div>
          <AgentCore productsCount={products.length} lowStock={lowStock} />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <StatCard label="Clientes" value={String(customers.length)} icon={Users} accent="amber" />
            <StatCard
              label="Stock"
              value={String(lowStock)}
              hint={lowStock === 0 ? `estable en ${products.length} productos` : `${lowStock} de ${products.length} productos`}
              icon={TriangleAlert}
              accent="rose"
            />
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.25fr_0.75fr]">
          <div className="space-y-6">
            <div>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-mono text-xs font-semibold uppercase tracking-[0.16em] text-slate-300">
                  Pedidos recientes
                </h2>
                <Link href="/pedidos" className="font-mono text-xs font-medium uppercase tracking-[0.12em] text-hud-400 hover:text-hud-300">
                  Ver todos →
                </Link>
              </div>
              <RecentOrdersList orders={orders.slice(0, 6)} />
            </div>
          </div>

          <div className="space-y-6">
            <div>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-mono text-xs font-semibold uppercase tracking-[0.16em] text-slate-300">
                  Actividad reciente
                </h2>
                <Link href="/auditoria" className="font-mono text-xs font-medium uppercase tracking-[0.12em] text-hud-400 hover:text-hud-300">
                  Ver todo →
                </Link>
              </div>
              <HudPanel className="p-4">
                <ActivityFeed logs={logs} />
              </HudPanel>
            </div>
          </div>
        </div>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <DashboardHero restaurantName="El Olivar Grill" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
