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
  items: OrderItemOut[];
}

// Superset del roadmap (docs/05-modelo-dominio.md); el backend hoy solo
// produce "confirmed"/"scheduled", el resto queda listo para cuando el
// dominio los emita (preparing/ready/delivered/etc).
export type OrderStatus =
  | "draft"
  | "pending_confirmation"
  | "confirmed"
  | "preparing"
  | "ready"
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
