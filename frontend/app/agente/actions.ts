"use server";

import { revalidatePath } from "next/cache";
import { ApiError, api } from "@/lib/api";
import type { AgentMessageIn, AgentTurnOut } from "@/lib/types";

export interface SendTurnResult {
  ok: boolean;
  data?: AgentTurnOut;
  error?: string;
}

export async function sendAgentTurnAction(payload: AgentMessageIn): Promise<SendTurnResult> {
  try {
    const data = await api.agent.turn(payload);

    // Cuando un pedido se confirma o cancela, refrescamos las paginas que
    // dependen de esos datos para que la proxima visita ya los muestre.
    if (data.status === "closed") {
      revalidatePath("/");
      revalidatePath("/pedidos");
      revalidatePath("/clientes");
      revalidatePath("/auditoria");
    }

    return { ok: true, data };
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error inesperado hablando con el agente.";
    return { ok: false, error: message };
  }
}
