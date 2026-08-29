import "server-only";

import type {
  AgentMessageIn,
  AgentTurnOut,
  AuditLogEntry,
  ConversationDetailOut,
  ConversationOut,
  CustomerCreateIn,
  CustomerOut,
  CustomerUpdateIn,
  BusinessInfoOut,
  OrderOut,
  ProductOut,
  WorkflowRunEntry,
} from "./types";

// Solo se resuelve en el servidor de Next.js (server components / server
// actions): por eso no lleva el prefijo NEXT_PUBLIC_ y "server-only" revienta
// el build si alguien lo importa desde un client component por error.
const API_BASE = process.env.API_URL ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `No se pudo conectar con el backend en ${API_BASE}. ¿Esta corriendo uvicorn?`);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // el body no era JSON, nos quedamos con statusText
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (entries.length === 0) return "";
  const search = new URLSearchParams(entries.map(([k, v]) => [k, String(v)]));
  return `?${search.toString()}`;
}

export const api = {
  products: {
    list: (q?: string) => request<ProductOut[]>(`/products${qs({ q })}`),
  },
  customers: {
    list: (q?: string, limit = 100) => request<CustomerOut[]>(`/customers${qs({ q, limit })}`),
    create: (data: CustomerCreateIn) =>
      request<CustomerOut>("/customers", { method: "POST", body: JSON.stringify(data) }),
    update: (id: number, data: CustomerUpdateIn) =>
      request<CustomerOut>(`/customers/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    remove: (id: number) => request<void>(`/customers/${id}`, { method: "DELETE" }),
  },
  orders: {
    list: (limit = 50) => request<OrderOut[]>(`/orders${qs({ limit })}`),
    get: (id: number) => request<OrderOut>(`/orders/${id}`),
    updateStatus: (id: number, status: string) =>
      request<OrderOut>(`/orders/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  },
  agent: {
    turn: (payload: AgentMessageIn) =>
      request<AgentTurnOut>("/agent/turn", { method: "POST", body: JSON.stringify(payload) }),
  },
  conversations: {
    list: (limit = 50) => request<ConversationOut[]>(`/conversations${qs({ limit })}`),
    get: (id: string) => request<ConversationDetailOut>(`/conversations/${encodeURIComponent(id)}`),
  },
  system: {
    auditLogs: (limit = 50) => request<AuditLogEntry[]>(`/system/audit-logs${qs({ limit })}`),
    workflowRuns: (limit = 20) => request<WorkflowRunEntry[]>(`/system/workflow-runs${qs({ limit })}`),
    businessInfo: () => request<BusinessInfoOut>("/system/business-info"),
  },
};
