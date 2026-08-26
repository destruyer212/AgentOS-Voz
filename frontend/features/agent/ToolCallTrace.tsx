"use client";

import { ChevronDown, Wrench } from "lucide-react";
import { useState } from "react";
import { CodeBlock } from "@/components/CodeBlock";
import type { ToolCallOut } from "@/lib/types";

export function ToolCallTrace({ calls }: { calls: ToolCallOut[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  if (calls.length === 0) {
    return <p className="text-xs text-slate-600">Sin tool calls en este turno.</p>;
  }

  return (
    <div className="space-y-2">
      {calls.map((call, idx) => {
        const isOpen = openIndex === idx;
        const isError = "error" in call.result;
        return (
          <div key={idx} className="overflow-hidden rounded-lg border border-surface-700 bg-surface-950/40">
            <button
              type="button"
              onClick={() => setOpenIndex(isOpen ? null : idx)}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
            >
              <span className="flex items-center gap-2 truncate font-mono text-xs text-slate-300">
                <Wrench size={12} className={isError ? "text-accent-rose shrink-0" : "text-accent-teal shrink-0"} />
                <span className="truncate">{call.name}</span>
              </span>
              <ChevronDown
                size={14}
                className={`shrink-0 text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`}
              />
            </button>
            {isOpen && (
              <div className="animate-fade-in space-y-2 border-t border-surface-800 p-3">
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-600">Argumentos</p>
                  <CodeBlock data={call.arguments} />
                </div>
                <div>
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-600">Resultado</p>
                  <CodeBlock data={call.result} />
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
