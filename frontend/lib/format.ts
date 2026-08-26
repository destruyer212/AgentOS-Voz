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
  "order.confirm": "Pedido confirmado",
  "order.cancel": "Pedido cancelado",
  "order.unclear": "Sin definir",
  smalltalk: "Conversación",
  handoff: "Transferencia a humano",
};

export function intentLabel(intent: string): string {
  return INTENT_LABEL[intent] ?? intent;
}
