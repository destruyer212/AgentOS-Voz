// Espejo de los schemas Pydantic del backend (app/domain/schemas.py).
// Mantener sincronizado a mano: es un proyecto chico y un generador de
// tipos desde OpenAPI seria sobre-ingenieria en este punto.

export interface ProductOut {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  price: number;
  category: string;
  stock_available: number;
}

export interface CustomerOut {
  id: number;
  name: string;
  phone: string | null;
  address: string | null;
  notes: string | null;
}

export interface CustomerCreateIn {
  name: string;
  phone?: string | null;
  address?: string | null;
  notes?: string | null;
}

export interface CustomerUpdateIn {
  name?: string;
  phone?: string | null;
  address?: string | null;
  notes?: string | null;
}

export interface OrderItemOut {
  product_id: number;
  product_name: string;
  quantity: number;
  unit_price: number;
  notes: string | null;
}

export interface OrderOut {
  id: number;
  customer_id: number | null;
  customer_name: string | null;
  conversation_id: string | null;
  status: OrderStatus;
  requested_time: string | null;
  fulfillment_type: "delivery" | "pickup" | string | null;
  delivery_address: string | null;
  payment_method: "efectivo" | "yape" | "plin" | "tarjeta" | string | null;
  total: number;
  // Aviso de WhatsApp real (ver app/integrations/wsp_notifications.py) --
  // null mientras el aviso todavia no se intento (corre en paralelo fuera
  // del turno que confirma el pedido).
  whatsapp_status: WhatsappStatus | null;
  whatsapp_sent_at: string | null;
  items: OrderItemOut[];
}

export type WhatsappStatus = "sent" | "failed" | "skipped_not_configured" | "skipped_no_phone" | string;

// Espejo de InvoiceOut (backend/app/domain/invoicing_schemas.py) -- solo
// los campos que de verdad se muestran en el panel de Llamadas.
export type InvoiceDocumentType = "boleta" | "factura" | "nota_credito" | "nota_debito" | string;
export type SunatStatus = "draft" | "sent" | "accepted" | "pending" | "rejected" | "voided" | string;

export interface InvoiceOut {
  id: number;
  order_id: number | null;
  document_type: InvoiceDocumentType;
  serie: string;
  numero: number;
  cliente_tipo_doc: string;
  cliente_numero_doc: string | null;
  cliente_denominacion: string;
  total: number;
  sunat_status: SunatStatus;
  sunat_message: string | null;
  sunat_pdf_a4_url: string | null;
  sunat_pdf_ticket_url: string | null;
  created_at: string;
}

// Flujo real cocina -> motorizado -> entregado (ver panel de Pedidos y
// backend/app/domain/services.py, _ORDER_STATUS_TRANSITIONS -- unica fuente
// de verdad de que salto es valido desde cada estado).
export type OrderStatus =
  | "draft"
  | "pending_confirmation"
  | "confirmed"
  | "preparing"
  | "ready"
  | "dispatched"
  | "scheduled"
  | "delivered"
  | "cancelled"
  | "failed";

export interface ToolCallOut {
  name: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
}

export type ConversationStatus =
  | "collecting"
  | "need_name"
  | "need_fulfillment"
  | "need_address"
  | "need_payment"
  | "awaiting_confirmation"
  | "closed";

export interface AgentTurnOut {
  response: string;
  intent: string;
  missing: string[];
  tool_calls: ToolCallOut[];
  order: OrderOut | null;
  conversation_id: string;
  status: ConversationStatus;
}

export interface AgentMessageIn {
  message: string;
  conversation_id?: string;
  customer_phone?: string;
  customer_name?: string;
  channel?: "web" | "phone";
}

export type ConversationChannel = "web" | "phone" | string;

export interface ConversationOut {
  id: string;
  channel: ConversationChannel;
  status: "active" | "closed" | string;
  detail_status: ConversationStatus | null;
  customer_name: string | null;
  customer_phone: string | null;
  outcome: string | null;
  turns: number;
  last_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationTurnOut {
  role: "cliente" | "agente" | "sistema";
  text: string;
}

export interface ConversationDetailOut extends ConversationOut {
  transcript: ConversationTurnOut[];
  order: OrderOut | null;
  invoice: InvoiceOut | null;
}

export interface BusinessInfoOut {
  restaurant_name: string;
  day_name: string;
  is_open: boolean;
  open_time: string;
  close_time: string;
}

export interface AuditLogEntry {
  id: number;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  detail: string;
  created_at: string;
}

export interface WorkflowRunEntry {
  id: number;
  workflow_key: string;
  status: "completed" | "failed" | string;
  trace: string;
  created_at: string;
}

export interface WorkflowStepTrace {
  key: string;
  type: string;
  status: string;
  detail?: string | null;
  tool?: string | null;
  arguments?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
}
