import { Bike, CheckCircle2, ChefHat, PackageCheck, XCircle } from "lucide-react";
import type { ComponentType } from "react";
import type { OrderOut, OrderStatus } from "@/lib/types";

// Un solo "siguiente paso" por estado (nunca un desplegable libre): asi
// cocina/mostrador no pueden saltarse pasos por accidente -- el backend
// tambien lo valida (ver _ORDER_STATUS_TRANSITIONS en services.py), esto
// solo evita mostrar botones que igual el servidor rechazaria. "dispatched"
// (sale con el motorizado) dispara el aviso de WhatsApp "ya salió, ~30
// min"; "ready" en recojo dispara el aviso de "ya está listo".
//
// Compartido entre las 3 vistas de pedidos (admin en /pedidos, cocina en
// /cocina, recepcion en /recepcion) para que ninguna se desincronice de lo
// que el backend realmente acepta -- ver OrderStatusForm.tsx.
export const TERMINAL_STATUSES: OrderStatus[] = ["delivered", "cancelled", "failed"];

export interface NextAction {
  status: OrderStatus;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  tone: "primary" | "danger";
}

export function getNextActions(order: OrderOut): NextAction[] {
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

// Reparto de pantallas por rol (ver Sidebar.tsx y app/cocina, app/recepcion):
// cocina se queda con el tramo de cocinar -- aceptar el pedido y avisar
// cuando la comida esta lista o sale con el motorizado. Recepcion se queda
// con las puntas: confirmar pedidos que todavia no pasaron por el agente de
// voz (canal web a medio llenar, o algo armado a mano desde /pedidos) y
// cerrar la entrega/recojo frente al cliente. El admin en /pedidos sigue
// viendo TODO, sin ningun filtro de estos dos.
export const KITCHEN_STATUSES: OrderStatus[] = ["confirmed", "scheduled", "preparing"];
export const RECEPTION_STATUSES: OrderStatus[] = ["draft", "pending_confirmation", "ready", "dispatched"];

export function isKitchenOrder(order: OrderOut): boolean {
  return KITCHEN_STATUSES.includes(order.status as OrderStatus);
}

export function isReceptionOrder(order: OrderOut): boolean {
  return RECEPTION_STATUSES.includes(order.status as OrderStatus);
}
