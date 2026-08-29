import { NextResponse } from "next/server";
import { api } from "@/lib/api";

// Ruta liviana solo para que componentes de cliente (sidebar, notificacion
// de llamada entrante) puedan sondear "hay una llamada activa ahora mismo?"
// sin exponer la URL real del backend al navegador -- reusa el mismo
// api.conversations.list() server-only que ya usa el resto del panel.
export const dynamic = "force-dynamic";

export interface ActiveCallSummary {
  id: string;
  channel: string;
  customer_name: string | null;
  customer_phone: string | null;
  detail_status: string | null;
  created_at: string;
}

export async function GET() {
  try {
    const conversations = await api.conversations.list(30);
    const active: ActiveCallSummary[] = conversations
      .filter((c) => c.status === "active")
      .map((c) => ({
        id: c.id,
        channel: c.channel,
        customer_name: c.customer_name,
        customer_phone: c.customer_phone,
        detail_status: c.detail_status,
        created_at: c.created_at,
      }));
    return NextResponse.json({ active });
  } catch {
    // Si el backend esta caido no queremos que el sondeo del cliente truene
    // en bucle -- simplemente reportamos "sin llamadas activas".
    return NextResponse.json({ active: [] });
  }
}
