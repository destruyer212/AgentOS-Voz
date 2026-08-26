"use client";

import { ChevronDown, GitBranch, Workflow } from "lucide-react";
import { useState } from "react";
import { CodeBlock } from "@/components/CodeBlock";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Badge";
import type { WorkflowRunEntry, WorkflowStepTrace } from "@/lib/types";

// El campo de fecha llega ya formateado desde el server component padre
// (ver app/auditoria/page.tsx): Intl.DateTimeFormat puede diferir en un
// caracter invisible (NBSP vs espacio) entre el ICU de Node y el del
// navegador, y como este es un client component ese desfase rompe la
// hidratacion. Formatear en el server, que nunca se re-hidrata, lo evita.
type WorkflowRunWithLabel = WorkflowRunEntry & { createdAtLabel: string };

function parseTrace(raw: string): WorkflowStepTrace[] {
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as WorkflowStepTrace[]) : [];
  } catch {
    return [];
  }
}

export function WorkflowRunsTable({ runs }: { runs: WorkflowRunWithLabel[] }) {
  const [expanded, setExpanded] = useState<number | null>(runs[0]?.id ?? null);

  if (runs.length === 0) {
    return (
      <EmptyState
        icon={Workflow}
        title="Sin ejecuciones todavía"
        description="El workflow restaurant_order_fulfillment corre cada vez que un pedido se confirma en la pestaña Agente."
      />
    );
  }

  return (
    <div className="space-y-3">
      {runs.map((run) => {
        const steps = parseTrace(run.trace);
        const isOpen = expanded === run.id;
        return (
          <div key={run.id} className="overflow-hidden rounded-xl border border-surface-700 bg-surface-900">
            <button
              type="button"
              onClick={() => setExpanded(isOpen ? null : run.id)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left transition-colors hover:bg-surface-800/60"
            >
              <div className="flex items-center gap-3">
                <GitBranch size={16} className="text-brand-400" />
                <div>
                  <p className="text-sm font-medium text-slate-200">{run.workflow_key}</p>
                  <p className="text-xs text-slate-500">{run.createdAtLabel}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Pill tone={run.status === "completed" ? "success" : "danger"}>
                  {run.status === "completed" ? "completado" : "falló"}
                </Pill>
                <ChevronDown
                  size={16}
                  className={`text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`}
                />
              </div>
            </button>

            {isOpen && (
              <div className="animate-fade-in space-y-2 border-t border-surface-800 p-4">
                {steps.map((step, idx) => (
                  <div key={idx} className="rounded-lg border border-surface-800 bg-surface-950/50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-slate-400">{step.key}</span>
                        <span className="text-[11px] uppercase tracking-wide text-slate-600">{step.type}</span>
                      </div>
                      <Pill tone={step.status === "ok" ? "success" : "danger"}>{step.status}</Pill>
                    </div>
                    {step.tool && <p className="mt-1.5 text-xs text-slate-500">tool: {step.tool}</p>}
                    {step.detail && <p className="mt-1.5 text-xs text-accent-rose">{step.detail}</p>}
                    {step.arguments && (
                      <div className="mt-2">
                        <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-600">Argumentos</p>
                        <CodeBlock data={step.arguments} />
                      </div>
                    )}
                    {step.result && (
                      <div className="mt-2">
                        <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-600">Resultado</p>
                        <CodeBlock data={step.result} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
