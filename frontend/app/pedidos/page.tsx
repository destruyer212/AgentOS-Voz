import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { PageHeader } from "@/components/PageHeader";
import { OrdersTable } from "@/features/orders/OrdersTable";
import { ApiError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Pedidos" };

export default async function PedidosPage() {
  try {
    const orders = await api.orders.list(100);
    return (
      <div>
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
