import type { OrderStatus } from "./types";

const currencyFormatter = new Intl.NumberFormat("es-PE", {
  style: "currency",
  currency: "PEN",
  minimumFractionDigits: 2,
});

export function formatCurrency(value: number): string {
  return currencyFormatter.format(value);
}

const dateTimeFormatter = new Intl.DateTimeFormat("es-PE", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDateTime(iso: string): string {
  try {
    // El backend guarda timestamps naive en UTC (SQLite); les agregamos
    // "Z" si no la traen para que el navegador los convierta a hora local.
    const withZone = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
    return dateTimeFormatter.format(new Date(withZone));
  } catch {
    return iso;
  }
}

export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  draft: "Borrador",
  pending_confirmation: "Por confirmar",
  confirmed: "Confirmado",
  preparing: "En preparación",
  ready: "Listo",
  scheduled: "Programado",
  delivered: "Entregado",
  cancelled: "Cancelado",
  failed: "Falló",
};

export function orderStatusLabel(status: string): string {
  return ORDER_STATUS_LABEL[status as OrderStatus] ?? status;
}

export const INTENT_LABEL: Record<string, string> = {
  "order.create": "Pedido en curso",
  "order.modify": "Pedido modificado",
  "order.clarify": "Aclarando pedido",
  "order.confirm": "Pedido confirmado",
  "order.cancel": "Pedido cancelado",
  "order.unclear": "Sin definir",
  "menu.inquiry": "Consultó el menú",
  "detail.unclear": "Sin definir",
  smalltalk: "Conversación",
  handoff: "Transferencia a humano",
};

export function intentLabel(intent: string): string {
  return INTENT_LABEL[intent] ?? intent;
}

export const PAYMENT_METHOD_LABEL: Record<string, string> = {
  efectivo: "Efectivo",
  yape: "Yape",
  plin: "Plin",
  tarjeta: "Tarjeta",
};

export function paymentMethodLabel(method: string): string {
  return PAYMENT_METHOD_LABEL[method] ?? method;
}

export const FULFILLMENT_LABEL: Record<string, string> = {
  delivery: "Delivery",
  pickup: "Recojo en local",
};

export function fulfillmentLabel(type: string): string {
  return FULFILLMENT_LABEL[type] ?? type;
}

// Etapas del flujo de una llamada/chat, en el orden real en que ocurren.
// Se derivan de datos reales del backend (status + detail_status del
// agente -- ver ConversationState.status en agents/runtime.py), nunca
// inventadas: si el backend no mando detail_status todavia (conversacion
// vieja, de antes de que existiera ese campo), cae en "connected" en vez
// de fingir una etapa que no se puede confirmar.
export type CallStageKey = "connected" | "choosing" | "details" | "confirming" | "confirmed" | "ended";

export interface CallStageInfo {
  key: CallStageKey;
  index: number; // 0-4, posicion en la barra de progreso (confirmed y ended comparten la ultima)
  label: string;
}

const STAGE_ORDER: CallStageKey[] = ["connected", "choosing", "details", "confirming", "confirmed"];

export const CALL_STAGE_LABEL: Record<CallStageKey, string> = {
  connected: "Llamada conectada",
  choosing: "Eligiendo productos",
  details: "Completando datos",
  confirming: "Confirmando pedido",
  confirmed: "Pedido confirmado",
  ended: "Llamada finalizada",
};

const DETAIL_STATUS_STAGE: Record<string, CallStageKey> = {
  collecting: "choosing",
  need_name: "details",
  need_fulfillment: "details",
  need_address: "details",
  need_payment: "details",
  awaiting_confirmation: "confirming",
};

export function callStage(input: {
  status: string;
  detail_status: string | null;
  outcome: string | null;
}): CallStageInfo {
  let key: CallStageKey;
  if (input.status === "closed") {
    key = input.outcome === "order.confirm" ? "confirmed" : "ended";
  } else {
    key = (input.detail_status && DETAIL_STATUS_STAGE[input.detail_status]) || "connected";
  }
  const index = STAGE_ORDER.indexOf(key === "ended" ? "confirmed" : key);
  return { key, index: index === -1 ? 0 : index, label: CALL_STAGE_LABEL[key] };
}
