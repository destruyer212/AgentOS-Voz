import { ArrowLeft } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { ChannelBadge, Pill } from "@/components/Badge";
import { HudPanel } from "@/components/HudPanel";
import { LiveRefresher } from "@/components/LiveRefresher";
import { OrderSummaryCard } from "@/features/agent/OrderSummaryCard";
import { CallFlowPipeline } from "@/features/conversations/CallFlowPipeline";
import { ConversationTranscript } from "@/features/conversations/ConversationTranscript";
import { ApiError, api } from "@/lib/api";
import { formatDateTime, intentLabel } from "@/lib/format";

export const metadata: Metadata = { title: "Llamada" };

export default async function LlamadaDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const conversationId = safeDecodeRouteParam(id);

  let convo;
  try {
    convo = await api.conversations.get(conversationId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <BackLink />
        <ApiErrorNotice message={message} />
      </div>
    );
  }

  const isActive = convo.status === "active";

  return (
    <div>
      <LiveRefresher active={isActive} intervalMs={2000} />
      <BackLink />

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <ChannelBadge channel={convo.channel} />
          <div>
            <p className="text-lg font-semibold text-white">
              {convo.customer_name ?? "Cliente sin registrar"}
            </p>
            {convo.customer_phone && (
              <p className="font-mono text-xs text-slate-500">{convo.customer_phone}</p>
            )}
          </div>
        </div>
        {isActive ? (
          <Pill tone="info">
            <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-hud-400" />
            En curso — actualizando en vivo
          </Pill>
        ) : (
          <Pill tone="neutral">{convo.outcome ? intentLabel(convo.outcome) : "Cerrada"}</Pill>
        )}
      </div>

      <div className="mb-6">
        <CallFlowPipeline
          status={convo.status}
          detailStatus={convo.detail_status}
          outcome={convo.outcome}
          order={convo.order}
          customerName={convo.customer_name}
          channel={convo.channel}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <HudPanel className="p-5">
          <ConversationTranscript turns={convo.transcript} />
        </HudPanel>

        <div className="space-y-4">
          <div className="border border-surface-700 bg-surface-900 p-4">
            <p className="mb-2.5 text-xs font-medium uppercase tracking-wide text-slate-500">Detalle</p>
            <dl className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-slate-500">Turnos</dt>
                <dd className="text-slate-300">{convo.turns}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-500">Inicio</dt>
                <dd className="text-slate-300">{formatDateTime(convo.created_at)}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-500">Última actividad</dt>
                <dd className="text-slate-300">{formatDateTime(convo.updated_at)}</dd>
              </div>
            </dl>
          </div>

          {convo.order ? (
            <OrderSummaryCard order={convo.order} />
          ) : (
            <div className="border border-dashed border-surface-600 p-4 text-center text-sm text-slate-500">
              {isActive ? "Todavía no se confirmó un pedido." : "Esta conversación no generó un pedido."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function safeDecodeRouteParam(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function BackLink() {
  return (
    <Link
      href="/llamadas"
      className="mb-5 inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200"
    >
      <ArrowLeft size={15} /> Volver a llamadas
    </Link>
  );
}
