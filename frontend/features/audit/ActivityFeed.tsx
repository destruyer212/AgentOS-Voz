import { Activity } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime } from "@/lib/format";
import type { AuditLogEntry } from "@/lib/types";

const ACTOR_DOT: Record<string, string> = {
  agent: "bg-brand-400",
  system: "bg-accent-teal",
};

export function ActivityFeed({ logs }: { logs: AuditLogEntry[] }) {
  if (logs.length === 0) {
    return (
      <EmptyState
        icon={Activity}
        title="Sin actividad todavía"
        description="Interactúa con el agente para ver eventos aquí."
      />
    );
  }

  return (
    <ol>
      {logs.map((log, idx) => (
        <li key={log.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${ACTOR_DOT[log.actor] ?? "bg-slate-500"}`} />
            {idx < logs.length - 1 && <span className="mt-1 w-px flex-1 bg-surface-700" />}
          </div>
          <div className="min-w-0 flex-1 pb-4">
            <p className="font-mono text-xs text-slate-300">{log.action}</p>
            <p className="truncate text-xs text-slate-500">{log.detail || `${log.entity_type} #${log.entity_id}`}</p>
            <p className="mt-0.5 text-[11px] text-slate-600">{formatDateTime(log.created_at)}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
