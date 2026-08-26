// Espejo de los schemas Pydantic del backend (app/domain/schemas.py).
// Mantener sincronizado a mano: es un proyecto chico y un generador de
// tipos desde OpenAPI seria sobre-ingenieria en este punto.

export interface ProductOut {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  price: number;
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
  status: OrderStatus;
  requested_time: string | null;
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

export type ConversationStatus = "collecting" | "awaiting_confirmation" | "closed";

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
