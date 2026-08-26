import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { AuditLogTable } from "@/features/audit/AuditLogTable";
import { WorkflowRunsTable } from "@/features/audit/WorkflowRunsTable";
import { ApiError, api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export const metadata: Metadata = { title: "Auditoría" };

export default async function AuditoriaPage() {
  try {
    const [logs, runs] = await Promise.all([api.system.auditLogs(100), api.system.workflowRuns(30)]);
    // WorkflowRunsTable es un client component: formateamos la fecha aqui,
    // en el server, para que nunca tenga que recalcularla al hidratar.
    const runsWithLabel = runs.map((run) => ({ ...run, createdAtLabel: formatDateTime(run.created_at) }));

    return (
      <div>
        <PageHeader
          title="Auditoría"
          description="Todo lo que el agente y el sistema hicieron, reconstruible paso a paso."
        />
        <Tabs
          tabs={[
            { id: "actividad", label: `Actividad (${logs.length})`, content: <AuditLogTable logs={logs} /> },
            {
              id: "workflows",
              label: `Ejecuciones de workflow (${runs.length})`,
              content: <WorkflowRunsTable runs={runsWithLabel} />,
            },
          ]}
        />
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Auditoría" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
