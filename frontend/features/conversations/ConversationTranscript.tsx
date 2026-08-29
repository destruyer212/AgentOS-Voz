"use client";

import { Bot, User } from "lucide-react";
import { useEffect, useRef } from "react";
import type { ConversationTurnOut } from "@/lib/types";

// "use client" + auto-scroll: en una llamada en curso, LiveRefresher trae
// turnos nuevos cada pocos segundos (ver components/LiveRefresher.tsx). Sin
// esto, el usuario tenia que scrollear a mano cada vez para ver el mensaje
// mas reciente -- molesto justo cuando se quiere seguir la conversacion en
// vivo, que es el caso de uso principal de esta vista.
export function ConversationTranscript({ turns }: { turns: ConversationTurnOut[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  if (turns.length === 0) {
    return <p className="py-8 text-center text-sm text-slate-500">Sin mensajes todavía.</p>;
  }

  return (
    <div className="space-y-4">
      {turns.map((turn, idx) => {
        if (turn.role === "sistema") {
          return (
            <p key={idx} className="text-center text-xs text-slate-600">
              {turn.text}
            </p>
          );
        }

        const isClient = turn.role === "cliente";
        return (
          <div key={idx} className={`flex animate-fade-in items-end gap-2 ${isClient ? "justify-end" : "justify-start"}`}>
            {!isClient && (
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-500/15 text-brand-400">
                <Bot size={13} />
              </span>
            )}
            <div
              className={`max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                isClient
                  ? "rounded-br-sm bg-brand-500 text-white"
                  : "rounded-bl-sm border border-surface-700 bg-surface-800 text-slate-200"
              }`}
            >
              {turn.text}
            </div>
            {isClient && (
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-700 text-slate-400">
                <User size={13} />
              </span>
            )}
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
