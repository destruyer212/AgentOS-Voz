import { ScrollText } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime } from "@/lib/format";
import type { AuditLogEntry } from "@/lib/types";

const ACTOR_STYLES: Record<string, string> = {
  agent: "text-brand-400",
  system: "text-accent-teal",
};

export function AuditLogTable({ logs }: { logs: AuditLogEntry[] }) {
  if (logs.length === 0) {
    return (
      <EmptyState
        icon={ScrollText}
        title="Sin eventos todavía"
        description="Cada acción del agente o del sistema (pedido creado, stock movido, notificación enviada) queda registrada aquí."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-surface-700 bg-surface-900">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-700 text-xs uppercase tracking-wide text-slate-500">
            <th className="px-4 py-3 font-medium">Cuándo</th>
            <th className="px-4 py-3 font-medium">Actor</th>
            <th className="px-4 py-3 font-medium">Acción</th>
            <th className="px-4 py-3 font-medium">Entidad</th>
            <th className="px-4 py-3 font-medium">Detalle</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-800">
          {logs.map((log) => (
            <tr key={log.id} className="transition-colors hover:bg-surface-800/60">
              <td className="whitespace-nowrap px-4 py-3 text-slate-500">{formatDateTime(log.created_at)}</td>
              <td className={`whitespace-nowrap px-4 py-3 font-medium ${ACTOR_STYLES[log.actor] ?? "text-slate-300"}`}>
                {log.actor}
              </td>
              <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-300">{log.action}</td>
              <td className="whitespace-nowrap px-4 py-3 text-slate-400">
                {log.entity_type} #{log.entity_id}
              </td>
              <td className="max-w-sm truncate px-4 py-3 text-slate-500">{log.detail || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
