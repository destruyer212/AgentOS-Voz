"use client";

import { Phone } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ChannelBadge, Pill } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import {
  CONVERSATION_BUCKET_LABEL,
  callStage,
  conversationBucket,
  conversationOutcomeLabel,
  formatDateTime,
  type ConversationBucket,
} from "@/lib/format";
import type { ConversationOut } from "@/lib/types";

const BUCKET_ORDER: ConversationBucket[] = ["live", "confirmed", "unconfirmed", "handoff"];
const BUCKET_TONE: Record<ConversationBucket, "info" | "success" | "neutral" | "danger"> = {
  live: "info",
  confirmed: "success",
  unconfirmed: "neutral",
  handoff: "danger",
};

export function ConversationsTable({ conversations }: { conversations: ConversationOut[] }) {
  const buckets = useMemo(() => {
    const present = new Set(conversations.map((c) => conversationBucket(c)));
    return BUCKET_ORDER.filter((b) => present.has(b));
  }, [conversations]);
  const [active, setActive] = useState<ConversationBucket | null>(null);

  if (conversations.length === 0) {
    return (
      <EmptyState
        icon={Phone}
        title="Todavía no hay conversaciones"
        description="Aparecen aquí en cuanto alguien hable con el agente, por chat o por teléfono."
      />
    );
  }

  const grouped = active
    ? [{ bucket: active, items: conversations.filter((c) => conversationBucket(c) === active) }]
    : BUCKET_ORDER.filter((b) => buckets.includes(b)).map((bucket) => ({
        bucket,
        items: conversations.filter((c) => conversationBucket(c) === bucket),
      }));

  return (
    <div>
      <div className="mb-5 flex flex-wrap gap-2">
        <BucketPill
          label={`Todas (${conversations.length})`}
          isActive={active === null}
          onClick={() => setActive(null)}
        />
        {buckets.map((bucket) => {
          const count = conversations.filter((c) => conversationBucket(c) === bucket).length;
          return (
            <BucketPill
              key={bucket}
              label={`${CONVERSATION_BUCKET_LABEL[bucket]} (${count})`}
              isActive={active === bucket}
              onClick={() => setActive(bucket)}
            />
          );
        })}
      </div>

      <div className="space-y-8">
        {grouped.map(({ bucket, items }) => (
          <section key={bucket}>
            <div className="mb-3 flex items-center gap-2">
              <span className="h-1 w-1 rounded-full bg-hud-400" />
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {CONVERSATION_BUCKET_LABEL[bucket]}
              </h2>
              <span className="text-xs text-slate-600">{items.length}</span>
            </div>
            <ConversationGroupTable conversations={items} />
          </section>
        ))}
      </div>
    </div>
  );
}

function BucketPill({ label, isActive, onClick }: { label: string; isActive: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
        isActive
          ? "border-hud-500/50 bg-hud-500/15 text-hud-400"
          : "border-surface-700 bg-surface-800 text-slate-400 hover:border-surface-600 hover:text-slate-200"
      }`}
    >
      {label}
    </button>
  );
}

function ConversationGroupTable({ conversations }: { conversations: ConversationOut[] }) {
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
            {conversations.map((convo) => {
              const bucket = conversationBucket(convo);
              return (
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
                        {bucket === "live" ? (
                          <Pill tone="info">
                            <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-brand-400" />
                            {callStage({ status: convo.status, detail_status: convo.detail_status, outcome: convo.outcome }).label}
                          </Pill>
                        ) : (
                          <Pill tone={BUCKET_TONE[bucket]}>{conversationOutcomeLabel(convo)}</Pill>
                        )}
                      </span>
                      <span className="whitespace-nowrap text-slate-500">{convo.turns}</span>
                      <span className="whitespace-nowrap text-slate-500">{formatDateTime(convo.updated_at)}</span>
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
