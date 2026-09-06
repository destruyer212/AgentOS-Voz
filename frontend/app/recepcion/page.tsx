import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { LiveRefresher } from "@/components/LiveRefresher";
import { PageHeader } from "@/components/PageHeader";
import { OrderBoard, type BoardColumn } from "@/features/orders/OrderBoard";
import { RECEPTION_STATUSES, isReceptionOrder } from "@/features/orders/orderActions";
import { ApiError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Recepción" };

// Recepcion se queda con las puntas del flujo -- ver
// features/orders/orderActions.ts: confirmar pedidos que todavia no
// pasaron por el agente de voz (canal web a medio llenar, o algo armado a
// mano desde /pedidos), y cerrar la entrega/recojo frente al cliente. Lo
// que esta cocinandose es trabajo de cocina, no de recepcion.
const COLUMNS: BoardColumn[] = [
  { key: "por_confirmar", title: "Por confirmar", statuses: ["draft", "pending_confirmation"] },
  { key: "listo_recojo", title: "Listo para recoger", statuses: ["ready"] },
  { key: "en_camino", title: "En camino (motorizado)", statuses: ["dispatched"] },
];

export default async function RecepcionPage() {
  try {
    const allOrders = await api.orders.list(100);
    const orders = allOrders.filter(isReceptionOrder);
    const hasActive = orders.some((o) => RECEPTION_STATUSES.includes(o.status));
    return (
      <div>
        <LiveRefresher active={hasActive} intervalMs={4000} />
        <PageHeader
          title="Recepción"
          description={`${orders.length} pedido${orders.length === 1 ? "" : "s"} por atender`}
        />
        <OrderBoard
          orders={orders}
          columns={COLUMNS}
          emptyTitle="No hay pedidos por atender"
          emptyDescription="Los pedidos por confirmar y los que ya están listos para entregar aparecen aquí."
        />
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Recepción" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
