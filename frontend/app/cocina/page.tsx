import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { LiveRefresher } from "@/components/LiveRefresher";
import { PageHeader } from "@/components/PageHeader";
import { OrderBoard, type BoardColumn } from "@/features/orders/OrderBoard";
import { KITCHEN_STATUSES, isKitchenOrder } from "@/features/orders/orderActions";
import { ApiError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Cocina" };

// Cocina solo ve el tramo de "hay que cocinar esto" -- ver
// features/orders/orderActions.ts. Pedidos nuevos sin confirmar (canal web
// a medio llenar) o ya listos/en camino son trabajo de recepcion, no de
// cocina.
const COLUMNS: BoardColumn[] = [
  { key: "por_aceptar", title: "Por aceptar", statuses: ["confirmed", "scheduled"] },
  { key: "preparando", title: "En preparación", statuses: ["preparing"] },
];

export default async function CocinaPage() {
  try {
    const allOrders = await api.orders.list(100);
    const orders = allOrders.filter(isKitchenOrder);
    // Mientras haya algo pendiente de aceptar o cocinando, se refresca sola
    // -- el cocinero no tiene por que estar tocando la pantalla para ver
    // llegar un pedido nuevo.
    const hasActive = orders.some((o) => KITCHEN_STATUSES.includes(o.status));
    return (
      <div>
        <LiveRefresher active={hasActive} intervalMs={4000} />
        <PageHeader
          title="Cocina"
          description={`${orders.length} pedido${orders.length === 1 ? "" : "s"} por cocinar`}
        />
        <OrderBoard
          orders={orders}
          columns={COLUMNS}
          emptyTitle="No hay pedidos por cocinar"
          emptyDescription="En cuanto se confirme un pedido nuevo, aparece aquí solo."
        />
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Cocina" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
