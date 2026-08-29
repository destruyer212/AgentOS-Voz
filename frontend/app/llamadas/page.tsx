import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { LiveRefresher } from "@/components/LiveRefresher";
import { PageHeader } from "@/components/PageHeader";
import { ConversationsTable } from "@/features/conversations/ConversationsTable";
import { ApiError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Llamadas" };

export default async function LlamadasPage() {
  try {
    const conversations = await api.conversations.list(100);
    const hasActive = conversations.some((c) => c.status === "active");

    return (
      <div>
        <LiveRefresher active={hasActive} intervalMs={3000} />
        <PageHeader
          title="Llamadas y conversaciones"
          description="Chat web y telefonía comparten el mismo agente — aquí se ve el flujo completo de cada una, en vivo mientras está en curso."
        />
        <ConversationsTable conversations={conversations} />
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Llamadas y conversaciones" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
