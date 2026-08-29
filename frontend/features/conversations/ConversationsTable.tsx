import { Phone } from "lucide-react";
import Link from "next/link";
import { ChannelBadge, Pill } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime, intentLabel } from "@/lib/format";
import type { ConversationOut } from "@/lib/types";

export function ConversationsTable({ conversations }: { conversations: ConversationOut[] }) {
  if (conversations.length === 0) {
    return (
      <EmptyState
        icon={Phone}
        title="Todavía no hay conversaciones"
        description="Aparecen aquí en cuanto alguien hable con el agente, por chat o por teléfono."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-surface-700 bg-surface-900">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-surface-700 text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-3 font-medium">Canal</th>
              <th className="px-4 py-3 font-medium">Cliente</th>
              <th className="px-4 py-3 font-medium">Último mensaje</th>
              <th className="px-4 py-3 font-medium">Estado</th>
              <th className="px-4 py-3 font-medium">Turnos</th>
              <th className="px-4 py-3 font-medium">Cuándo</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-800">
            {conversations.map((convo) => (
              <tr key={convo.id}>
                <td colSpan={6} className="p-0">
                  <Link
                    href={`/llamadas/${encodeURIComponent(convo.id)}`}
                    className="grid grid-cols-[auto_1fr_2fr_auto_auto_auto] items-center gap-4 px-4 py-3 transition-colors hover:bg-surface-800/60"
                  >
                    <ChannelBadge channel={convo.channel} />
                    <span className="truncate text-slate-200">
                      {convo.customer_name ?? <span className="text-slate-500">Sin registrar</span>}
                    </span>
                    <span className="truncate text-slate-400">{convo.last_message ?? "—"}</span>
                    <span>
                      {convo.status === "active" ? (
                        <Pill tone="info">
                          <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-brand-400" />
                          en curso
                        </Pill>
                      ) : (
                        <Pill tone="neutral">{convo.outcome ? intentLabel(convo.outcome) : "cerrada"}</Pill>
                      )}
                    </span>
                    <span className="whitespace-nowrap text-slate-500">{convo.turns}</span>
                    <span className="whitespace-nowrap text-slate-500">{formatDateTime(convo.updated_at)}</span>
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
