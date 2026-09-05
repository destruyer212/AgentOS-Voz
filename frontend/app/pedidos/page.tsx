import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { LiveRefresher } from "@/components/LiveRefresher";
import { PageHeader } from "@/components/PageHeader";
import { OrdersTable } from "@/features/orders/OrdersTable";
import { ApiError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Pedidos" };

const TERMINAL_STATUSES = ["delivered", "cancelled", "failed"];

export default async function PedidosPage() {
  try {
    const orders = await api.orders.list(100);
    // Pantalla de cocina/mostrador: mientras haya algun pedido en curso
    // (no cerrado), se refresca sola para que se vea avanzar sin que nadie
    // tenga que tocar la pantalla -- igual que /llamadas.
    const hasActive = orders.some((o) => !TERMINAL_STATUSES.includes(o.status));
    return (
      <div>
        <LiveRefresher active={hasActive} intervalMs={4000} />
        <PageHeader title="Pedidos" description={`${orders.length} pedido${orders.length === 1 ? "" : "s"} registrados`} />
        <OrdersTable orders={orders} />
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Pedidos" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
