"use client";

import { Bot, RotateCcw, Send, User } from "lucide-react";
import { useRef, useState, useTransition, type FormEvent } from "react";
import { sendAgentTurnAction } from "@/app/agente/actions";
import { Pill } from "@/components/Badge";
import { Spinner } from "@/components/Spinner";
import { intentLabel } from "@/lib/format";
import type { AgentTurnOut } from "@/lib/types";
import { OrderSummaryCard } from "./OrderSummaryCard";
import { ToolCallTrace } from "./ToolCallTrace";

interface ChatMessage {
  id: string;
  role: "user" | "agent" | "error";
  text: string;
}

const CONVERSATION_STATUS_LABEL: Record<string, string> = {
  collecting: "Recopilando pedido",
  need_name: "Pidiendo el nombre",
  need_fulfillment: "Preguntando delivery o recojo",
  need_address: "Pidiendo la dirección",
  need_payment: "Preguntando forma de pago",
  awaiting_confirmation: "Esperando confirmación",
  closed: "Conversación cerrada",
};

const STARTERS = [
  "Hola, quiero dos hamburguesas dobles, una sin cebolla, tres Inca Colas para las ocho",
  "Quiero hablar con una persona por favor",
];

function newId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [lastTurn, setLastTurn] = useState<AgentTurnOut | null>(null);
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [showCustomerFields, setShowCustomerFields] = useState(false);
  const [isPending, startTransition] = useTransition();
  const listRef = useRef<HTMLDivElement>(null);
  // Incrementado en reset(): si el usuario arranca "Nueva conversación"
  // mientras una respuesta anterior sigue en vuelo, la respuesta que llegue
  // tarde queda con un numero de sesion viejo y se descarta en vez de
  // colarse (conversationId y mensajes) en el chat nuevo que ya se ve en
  // pantalla.
  const sessionRef = useRef(0);

  function pushMessage(msg: ChatMessage) {
    setMessages((prev) => [...prev, msg]);
    queueMicrotask(() => {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
    });
  }

  function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || isPending) return;

    pushMessage({ id: newId(), role: "user", text: trimmed });
    setInput("");

    const session = sessionRef.current;
    startTransition(async () => {
      const result = await sendAgentTurnAction({
        message: trimmed,
        conversation_id: conversationId ?? undefined,
        customer_name: customerName || undefined,
        customer_phone: customerPhone || undefined,
      });

      if (session !== sessionRef.current) return; // se reseteo el chat mientras esperabamos la respuesta

      if (!result.ok || !result.data) {
        pushMessage({ id: newId(), role: "error", text: result.error ?? "Error desconocido." });
        return;
      }

      setConversationId(result.data.conversation_id);
      setLastTurn(result.data);
      pushMessage({ id: newId(), role: "agent", text: result.data.response });
    });
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  function reset() {
    sessionRef.current += 1;
    setMessages([]);
    setConversationId(null);
    setLastTurn(null);
    setInput("");
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
      <div className="flex h-[calc(100vh-13rem)] min-h-[420px] flex-col rounded-xl border border-surface-700 bg-surface-900">
        <div className="flex items-center justify-between border-b border-surface-700 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-500/15 text-brand-400">
              <Bot size={15} />
            </span>
            <div>
              <p className="text-sm font-medium text-slate-200">Sofía · Agente del restaurante</p>
              <p className="text-xs text-slate-500">
                {lastTurn ? CONVERSATION_STATUS_LABEL[lastTurn.status] ?? lastTurn.status : "Sin iniciar"}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={reset}
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-400 transition-colors hover:bg-surface-800 hover:text-slate-200"
          >
            <RotateCcw size={13} /> Nueva conversación
          </button>
        </div>

        <div ref={listRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-5">
          {messages.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <Bot size={28} className="mb-3 text-slate-600" />
              <p className="max-w-xs text-sm text-slate-400">
                Escribe como si fueras un cliente llamando al restaurante.
              </p>
              <div className="mt-4 flex max-w-md flex-wrap justify-center gap-2">
                {STARTERS.map((starter) => (
                  <button
                    key={starter}
                    type="button"
                    onClick={() => send(starter)}
                    className="rounded-full border border-surface-700 bg-surface-800 px-3 py-1.5 text-xs text-slate-400 transition-colors hover:border-brand-500 hover:text-slate-200"
                  >
                    {starter.length > 58 ? `${starter.slice(0, 55)}…` : starter}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <ChatBubble key={msg.id} message={msg} />
          ))}

          {isPending && (
            <div className="flex items-center gap-2 pl-1 text-xs text-slate-500">
              <Spinner size={13} /> Sofía está escribiendo…
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit} className="border-t border-surface-700 p-3">
          {showCustomerFields && (
            <div className="mb-2 grid grid-cols-2 gap-2 animate-fade-in">
              <input
                value={customerName}
                onChange={(e) => setCustomerName(e.target.value)}
                placeholder="Nombre del cliente (opcional)"
                className="form-input text-xs"
              />
              <input
                value={customerPhone}
                onChange={(e) => setCustomerPhone(e.target.value)}
                placeholder="Teléfono (opcional)"
                className="form-input text-xs"
              />
            </div>
          )}
          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={() => setShowCustomerFields((v) => !v)}
              title="Datos del cliente"
              aria-label="Datos del cliente"
              aria-pressed={showCustomerFields}
              className={`shrink-0 rounded-lg border px-2.5 py-2.5 transition-colors ${
                showCustomerFields
                  ? "border-brand-500 text-brand-400"
                  : "border-surface-700 text-slate-500 hover:text-slate-300"
              }`}
            >
              <User size={15} />
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder="Escribe un mensaje..."
              className="form-input resize-none"
            />
            <button
              type="submit"
              disabled={isPending || !input.trim()}
              aria-label="Enviar mensaje"
              className="btn-primary shrink-0"
            >
              <Send size={15} />
            </button>
          </div>
        </form>
      </div>

      <div className="space-y-4">
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
          <p className="mb-2.5 text-xs font-medium uppercase tracking-wide text-slate-500">Estado del turno</p>
          {lastTurn ? (
            <div className="space-y-2.5 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Intención</span>
                <Pill tone="info">{intentLabel(lastTurn.intent)}</Pill>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Conversación</span>
                <span className="font-mono text-xs text-slate-400">{lastTurn.conversation_id.slice(0, 8)}</span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-600">Todavía no inicia la conversación.</p>
          )}
        </div>

        {lastTurn && lastTurn.missing.length > 0 && (
          <div className="animate-fade-in rounded-xl border border-accent-amber/30 bg-accent-amber/5 p-4">
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-accent-amber">No encontrados</p>
            <ul className="space-y-1 text-sm text-slate-300">
              {lastTurn.missing.map((item, idx) => (
                <li key={idx}>• {item}</li>
              ))}
            </ul>
          </div>
        )}

        {lastTurn?.order && (
          <div className="animate-fade-in">
            <OrderSummaryCard order={lastTurn.order} />
          </div>
        )}

        {lastTurn && lastTurn.tool_calls.length > 0 && (
          <div className="animate-fade-in">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              Tool calls del último turno
            </p>
            <ToolCallTrace calls={lastTurn.tool_calls} />
          </div>
        )}
      </div>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  if (message.role === "error") {
    return (
      <div className="mx-auto max-w-md animate-fade-in rounded-lg border border-accent-rose/30 bg-accent-rose/10 px-3 py-2 text-center text-xs text-rose-200">
        {message.text}
      </div>
    );
  }

  const isUser = message.role === "user";
  return (
    <div className={`flex animate-fade-in ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? "rounded-br-sm bg-brand-500 text-white"
            : "rounded-bl-sm border border-surface-700 bg-surface-800 text-slate-200"
        }`}
      >
        {message.text}
      </div>
    </div>
  );
}
