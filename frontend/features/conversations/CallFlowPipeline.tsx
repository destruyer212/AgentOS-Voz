"use client";

import {
  CheckCircle2,
  CircleDashed,
  ClipboardList,
  Database,
  MapPin,
  PhoneCall,
  PhoneOff,
  Route,
  ShieldCheck,
  ShoppingCart,
  UserRound,
  Wallet,
  Workflow,
} from "lucide-react";
import type { ComponentType } from "react";
import { HudPanel } from "@/components/HudPanel";
import {
  CALL_STAGE_LABEL,
  callStage,
  formatCurrency,
  fulfillmentLabel,
  paymentMethodLabel,
  type CallStageKey,
} from "@/lib/format";
import type { OrderOut } from "@/lib/types";

const STEP_KEYS: CallStageKey[] = ["connected", "choosing", "details", "confirming", "confirmed"];

const STEP_ICON: Record<CallStageKey, ComponentType<{ size?: number; className?: string }>> = {
  connected: PhoneCall,
  choosing: ShoppingCart,
  details: ClipboardList,
  confirming: ShieldCheck,
  confirmed: CheckCircle2,
  ended: PhoneOff,
};

const DETAIL_COPY: Record<string, { label: string; waiting: string }> = {
  collecting: {
    label: "Cliente eligiendo productos",
    waiting: "El agente esta escuchando productos, cantidades y cambios.",
  },
  need_name: {
    label: "Falta nombre",
    waiting: "El agente debe capturar el nombre para registrar el pedido.",
  },
  need_fulfillment: {
    label: "Falta entrega",
    waiting: "El cliente debe elegir delivery o recojo en local.",
  },
  need_address: {
    label: "Falta direccion",
    waiting: "Como es delivery, el agente esta esperando la direccion.",
  },
  need_payment: {
    label: "Falta pago",
    waiting: "El agente debe confirmar si paga con efectivo, Yape, Plin o tarjeta.",
  },
  awaiting_confirmation: {
    label: "Esperando confirmacion",
    waiting: "El agente ya tiene el resumen y espera un si o no.",
  },
};

const DETAIL_STEPS = [
  { key: "need_name", label: "Nombre", icon: UserRound },
  { key: "need_fulfillment", label: "Entrega", icon: Route },
  { key: "need_address", label: "Direccion", icon: MapPin },
  { key: "need_payment", label: "Pago", icon: Wallet },
  { key: "awaiting_confirmation", label: "Confirmacion", icon: ShieldCheck },
];

interface FlowNode {
  key: string;
  title: string;
  subtitle: string;
  icon: ComponentType<{ size?: number; className?: string }>;
}

/**
 * Flujo grafico en tiempo real de una conversacion: en que etapa real esta
 * (segun el backend, no adivinado) -- conectada, eligiendo productos,
 * completando datos, confirmando, o cerrada. Vive en la pagina de detalle
 * de la llamada, refrescada por LiveRefresher mientras siga activa.
 */
export function CallFlowPipeline({
  status,
  detailStatus,
  outcome,
  order,
  customerName,
}: {
  status: string;
  detailStatus: string | null;
  outcome: string | null;
  order?: OrderOut | null;
  customerName?: string | null;
}) {
  const stage = callStage({ status, detail_status: detailStatus, outcome });
  const isEnded = stage.key === "ended";
  const isLive = status !== "closed";
  const liveCopy = detailStatus ? DETAIL_COPY[detailStatus] : null;
  const finalTitle = isEnded ? "Cierre sin pedido" : isLive ? "Crear orden" : "Pedido creado";
  const finalSubtitle = isEnded
    ? "Derivado, cancelado o sin confirmacion"
    : isLive
      ? "Se activa cuando el cliente confirma"
      : "Orden registrada en sistema";
  const currentIndex = stage.index;
  const itemsCount = order?.items.reduce((sum, item) => sum + item.quantity, 0) ?? 0;
  const payment = order?.payment_method ? paymentMethodLabel(order.payment_method) : null;
  const fulfillment = order?.fulfillment_type ? fulfillmentLabel(order.fulfillment_type) : null;

  const flowNodes: FlowNode[] = [
    {
      key: "connected",
      title: "Entrada",
      subtitle: "Canal abierto y cliente identificado",
      icon: PhoneCall,
    },
    {
      key: "choosing",
      title: "Pedido",
      subtitle: "Productos, cantidades y cambios",
      icon: ShoppingCart,
    },
    {
      key: "details",
      title: "Datos",
      subtitle: "Nombre, entrega, direccion y pago",
      icon: ClipboardList,
    },
    {
      key: "confirming",
      title: "Validacion",
      subtitle: "Resumen final antes de crear orden",
      icon: ShieldCheck,
    },
    {
      key: "final",
      title: finalTitle,
      subtitle: finalSubtitle,
      icon: isEnded ? PhoneOff : CheckCircle2,
    },
  ];

  return (
    <HudPanel className="overflow-hidden p-5" glow={isLive}>
      {isLive && (
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-hud-500/0 via-hud-500/[0.06] to-hud-500/0" />
      )}

      <div className="relative mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Workflow size={16} className="text-hud-400" />
            <p className="font-mono text-xs font-medium uppercase tracking-[0.28em] text-hud-300">
              Workflow de llamada
            </p>
          </div>
          <h2 className="mt-2 text-xl font-semibold text-white">Ruta operativa del cliente</h2>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Cada nodo representa una decision del agente; el nodo activo se ilumina mientras la llamada sigue abierta.
          </p>
        </div>
        {isLive ? (
          <span className="inline-flex items-center gap-1.5 rounded border border-hud-500/30 bg-hud-500/10 px-2.5 py-1.5 font-mono text-xs font-medium uppercase tracking-wide text-hud-300">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-hud-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-hud-400" />
            </span>
            En vivo
          </span>
        ) : (
          <span className="rounded border border-surface-600 bg-surface-800 px-2.5 py-1.5 font-mono text-xs font-medium uppercase tracking-wide text-slate-500">
            Finalizada
          </span>
        )}
      </div>

      <div className="relative grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_310px]">
        <div className="relative overflow-x-auto pb-1">
          <div className="grid min-w-[880px] grid-cols-[1fr_38px_1fr_38px_1fr_38px_1fr_38px_1fr] items-stretch">
            {flowNodes.map((node, index) => {
              const Icon = node.icon;
              const isLast = index === flowNodes.length - 1;
              const reached = index <= currentIndex;
              const isCurrent = index === currentIndex && !isEnded;
              const badge = isCurrent ? (isLive ? "Ahora" : "Final") : null;
              const isTerminalFailure = isEnded && isLast;

              return (
                <div key={node.key} className="contents">
                  <div
                    className={[
                      "relative min-h-[150px] border p-4 transition-all duration-500",
                      "bg-surface-950/70",
                      isTerminalFailure
                        ? "border-accent-rose/45 shadow-[0_0_24px_-12px_rgba(244,102,124,0.65)]"
                        : isCurrent
                          ? "border-hud-400/70 shadow-hud"
                          : reached
                            ? "border-hud-500/25"
                            : "border-surface-700",
                    ].join(" ")}
                  >
                    <div className="absolute left-0 top-0 h-5 w-px bg-hud-400/60" />
                    <div className="absolute left-0 top-0 h-px w-5 bg-hud-400/60" />
                    <div className="absolute bottom-0 right-0 h-5 w-px bg-hud-400/40" />
                    <div className="absolute bottom-0 right-0 h-px w-5 bg-hud-400/40" />
                    {isCurrent && <div className="hud-scanline" />}
                    <div className="relative flex h-full flex-col justify-between gap-5">
                      <div className="flex items-start justify-between gap-3">
                        <div
                          className={[
                            "flex h-11 w-11 items-center justify-center border",
                            isTerminalFailure
                              ? "border-accent-rose/40 bg-accent-rose/10 text-accent-rose"
                              : isCurrent
                                ? "border-hud-400/50 bg-hud-500/15 text-hud-300"
                                : reached
                                  ? "border-hud-500/25 bg-hud-500/10 text-hud-400"
                                  : "border-surface-600 bg-surface-800 text-slate-600",
                          ].join(" ")}
                        >
                          <Icon size={19} className={isCurrent ? "animate-pulse-slow" : ""} />
                        </div>
                        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-slate-600">
                          Nodo {String(index + 1).padStart(2, "0")}
                        </span>
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-base font-semibold text-white">{node.title}</h3>
                          {badge && (
                            <span className="rounded border border-hud-500/30 bg-hud-500/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-hud-300">
                              {badge}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-slate-500">{node.subtitle}</p>
                      </div>
                    </div>
                  </div>

                  {!isLast && (
                    <div className="flex items-center justify-center">
                      <div
                        className={[
                          "h-px w-full transition-colors duration-500",
                          index < currentIndex ? "bg-hud-400/70" : "bg-surface-700",
                        ].join(" ")}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-4 grid min-w-[880px] grid-cols-5 gap-2">
            {STEP_KEYS.map((key, index) => {
              const reached = index <= currentIndex;
              const isCurrent = index === currentIndex && !isEnded;
              const Icon = key === "confirmed" && isEnded ? STEP_ICON.ended : STEP_ICON[key];
              const label = key === "confirmed" && isEnded ? CALL_STAGE_LABEL.ended : CALL_STAGE_LABEL[key];

              return (
                <div
                  key={key}
                  className={[
                    "flex items-center gap-2 border px-3 py-2 text-xs",
                    key === "confirmed" && isEnded
                      ? "border-accent-rose/30 bg-accent-rose/10 text-accent-rose"
                      : isCurrent
                        ? "border-hud-400/50 bg-hud-500/10 text-hud-300"
                        : reached
                          ? "border-hud-500/20 bg-hud-500/[0.05] text-slate-300"
                          : "border-surface-700 bg-surface-900/70 text-slate-600",
                  ].join(" ")}
                >
                  <Icon size={14} />
                  <span className="truncate">{label}</span>
                </div>
              );
            })}
          </div>
        </div>

        <aside className="border border-surface-700 bg-surface-950/75 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-500">Estado actual</p>
              <h3 className="mt-1 text-lg font-semibold text-white">
                {isLive ? (liveCopy?.label ?? stage.label) : stage.label}
              </h3>
            </div>
            <div className="flex h-10 w-10 items-center justify-center border border-hud-500/25 bg-hud-500/10 text-hud-300">
              {isLive ? <CircleDashed size={18} className="animate-spin" /> : <Database size={18} />}
            </div>
          </div>

          <p className="mt-3 text-sm leading-relaxed text-slate-500">
            {isLive
              ? liveCopy?.waiting ?? "La llamada sigue activa y el agente espera el siguiente mensaje del cliente."
              : isEnded
                ? "La conversacion termino sin una orden confirmada."
                : "La conversacion termino con una orden registrada."}
          </p>

          <div className="mt-4 space-y-2">
            {DETAIL_STEPS.map((step) => {
              const Icon = step.icon;
              const active = detailStatus === step.key && isLive;
              const captured = detailCaptured(step.key, order, customerName, status, outcome);
              return (
                <div
                  key={step.key}
                  className={[
                    "flex items-center gap-2 border px-2.5 py-2 text-xs",
                    active
                      ? "border-hud-400/50 bg-hud-500/10 text-hud-300"
                      : captured
                        ? "border-accent-teal/25 bg-accent-teal/5 text-slate-300"
                        : "border-surface-700 bg-surface-900/60 text-slate-600",
                  ].join(" ")}
                >
                  <Icon size={14} className="shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{step.label}</span>
                  {active ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-hud-400" />
                  ) : captured ? (
                    <CheckCircle2 size={13} className="text-accent-teal" />
                  ) : (
                    <span className="h-1.5 w-1.5 rounded-full bg-surface-600" />
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-4 border-t border-surface-700 pt-4">
            <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-500">Datos capturados</p>
            <dl className="mt-3 space-y-2 text-sm">
              <SignalRow label="Cliente" value={order?.customer_name ?? customerName ?? "Pendiente"} />
              <SignalRow label="Items" value={itemsCount ? String(itemsCount) : "Pendiente"} />
              <SignalRow label="Entrega" value={fulfillment ?? "Pendiente"} />
              <SignalRow label="Pago" value={payment ?? "Pendiente"} />
              <SignalRow label="Total" value={order ? formatCurrency(order.total) : "Pendiente"} strong={Boolean(order)} />
            </dl>
          </div>
        </aside>
      </div>
    </HudPanel>
  );
}

function detailCaptured(
  key: string,
  order: OrderOut | null | undefined,
  customerName: string | null | undefined,
  status: string,
  outcome: string | null,
) {
  if (key === "need_name") return Boolean(order?.customer_name || customerName);
  if (key === "need_fulfillment") return Boolean(order?.fulfillment_type);
  if (key === "need_address") return order?.fulfillment_type === "pickup" || Boolean(order?.delivery_address);
  if (key === "need_payment") return Boolean(order?.payment_method);
  if (key === "awaiting_confirmation") return status === "closed" && outcome === "order.confirm";
  return false;
}

function SignalRow({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className={strong ? "font-semibold text-white" : "truncate text-right text-slate-300"}>{value}</dd>
    </div>
  );
}
