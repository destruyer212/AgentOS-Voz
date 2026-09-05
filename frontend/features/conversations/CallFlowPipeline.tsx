"use client";

import {
  Bike,
  CheckCircle2,
  ChefHat,
  CircleDashed,
  ClipboardList,
  Database,
  GitBranch,
  MapPin,
  MessageCircle,
  PackageCheck,
  PhoneCall,
  PhoneOff,
  Receipt,
  Route,
  ShieldCheck,
  ShoppingCart,
  Store,
  UserRound,
  Wallet,
  Workflow,
} from "lucide-react";
import type { ComponentType } from "react";
import { HudPanel } from "@/components/HudPanel";
import {
  callStage,
  formatCurrency,
  fulfillmentLabel,
  intentLabel,
  invoiceDocumentLabel,
  paymentMethodLabel,
  sunatStatusLabel,
  whatsappStatusLabel,
} from "@/lib/format";
import type { InvoiceOut, OrderOut } from "@/lib/types";

// Estados de pedido que ya no avanzan mas (ver
// backend/app/domain/services.py, _ORDER_STATUS_TRANSITIONS): una vez aca,
// el tramo cocina->motorizado->entregado del grafo deja de "viajar".
const ORDER_TERMINAL_STATUSES = new Set(["delivered", "cancelled", "failed"]);

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

// Geometria fija del grafo tipo n8n: 4 nodos en linea + una bifurcacion final
// (como el nodo "If" del workflow) hacia "pedido creado" (si) o "cierre sin
// pedido" (no). Si el pedido se creo, la rama "si" sigue 3 nodos mas
// (cocina -> motorizado/recojo -> entregado, el mismo pipeline del panel de
// Pedidos) -- ese tramo solo se dibuja cuando hay pedido; sin pedido el
// grafo queda igual que antes. Coordenadas fijas -> el SVG de conectores no
// necesita medir el DOM, igual que el min-width fijo que ya usaba este
// panel antes.
const VIEW_W = 1180;
const VIEW_W_WITH_FULFILLMENT = 2330;
const VIEW_H = 340;
const NODE = 68; // lado del cuadro-icono, como los nodos de n8n
const HALF = NODE / 2;
const ROW_Y = 150;
const BRANCH_TOP_Y = 55;
const BRANCH_BOTTOM_Y = 245;
// n6/n7 = comprobante SUNAT + aviso de WhatsApp (pasan casi al toque de
// confirmado el pedido, en paralelo -- ver AgentRuntime._issue_invoice_and_notify),
// n8/n9/n10 = el pipeline de cocina que ya existia.
const CENTERS = {
  n1: 110, n2: 340, n3: 570, n4: 800, n5: 1030,
  n6: 1260, n7: 1490, n8: 1720, n9: 1950, n10: 2180,
};

interface GraphNode {
  key: string;
  cx: number;
  cy: number;
  title: string;
  subtitle: string;
  icon: ComponentType<{ size?: number; className?: string }>;
}

/**
 * Flujo grafico en tiempo real de una conversacion, estilo grafo de nodos
 * (n8n): cada paso real del backend (status + detail_status, nunca
 * adivinado) es un nodo con icono, conectado por lineas curvas con la señal
 * "viajando" mientras la llamada sigue en curso. El ultimo nodo se bifurca
 * en dos salidas posibles -- pedido confirmado o cierre sin pedido -- igual
 * que un nodo de decision, y solo una de las dos se marca como recorrida.
 */
export function CallFlowPipeline({
  status,
  detailStatus,
  outcome,
  order,
  invoice,
  customerName,
  channel,
}: {
  status: string;
  detailStatus: string | null;
  outcome: string | null;
  order?: OrderOut | null;
  invoice?: InvoiceOut | null;
  customerName?: string | null;
  channel?: string | null;
}) {
  const stage = callStage({ status, detail_status: detailStatus, outcome });
  const isEnded = stage.key === "ended";
  const isLive = status !== "closed";
  const liveCopy = detailStatus ? DETAIL_COPY[detailStatus] : null;
  const currentIndex = stage.index;
  const itemsCount = order?.items.reduce((sum, item) => sum + item.quantity, 0) ?? 0;
  const payment = order?.payment_method ? paymentMethodLabel(order.payment_method) : null;
  const fulfillment = order?.fulfillment_type ? fulfillmentLabel(order.fulfillment_type) : null;

  const finalReached = currentIndex >= 4;
  const successTaken = finalReached && !isEnded;
  const failureTaken = finalReached && isEnded;

  // Tramo de cumplimiento (cocina -> motorizado/recojo -> entregado), el
  // mismo pipeline real que maneja el panel de Pedidos (ver
  // backend/app/domain/services.py, _ORDER_STATUS_TRANSITIONS). Solo se
  // dibuja si el pedido se llego a crear; sigue avanzando aunque la llamada
  // ya haya terminado, porque cocina/motorizado trabajan despues de colgar.
  // Escala -1..2: -1 = pedido creado, esperando que cocina lo acepte;
  // 0 = cocina preparandolo; 1 = salio con el motorizado / listo para
  // recoger; 2 = entregado (fin del pipeline). null/otro estado
  // (cancelado, fallido) = no aplica, no se sigue dibujando el avance.
  const showFulfillment = successTaken;
  const isDelivery = order?.fulfillment_type === "delivery";
  const fulfillmentStageIndex: -1 | 0 | 1 | 2 | null = (() => {
    if (!order) return null;
    switch (order.status) {
      case "confirmed":
      case "scheduled":
        return -1;
      case "preparing":
        return 0;
      case "ready":
      case "dispatched":
        return 1;
      case "delivered":
        return 2;
      default:
        return null; // cancelado/fallido/etc -- no seguimos avanzando aca
    }
  })();
  const orderIsLive = showFulfillment && order != null && !ORDER_TERMINAL_STATUSES.has(order.status);

  const nodes: GraphNode[] = [
    {
      key: "n1",
      cx: CENTERS.n1,
      cy: ROW_Y,
      title: "Entrada",
      subtitle: channel ? channel.toUpperCase() : "ENTRANTE",
      icon: PhoneCall,
    },
    {
      key: "n2",
      cx: CENTERS.n2,
      cy: ROW_Y,
      title: "Pedido",
      subtitle: "parser de items",
      icon: ShoppingCart,
    },
    {
      key: "n3",
      cx: CENTERS.n3,
      cy: ROW_Y,
      title: "Datos",
      subtitle: "nombre · entrega · pago",
      icon: ClipboardList,
    },
    {
      key: "n4",
      cx: CENTERS.n4,
      cy: ROW_Y,
      title: "Validación",
      subtitle: "¿pedido confirmado?",
      icon: GitBranch,
    },
  ];

  const successNode: GraphNode = {
    key: "n5a",
    cx: CENTERS.n5,
    cy: BRANCH_TOP_Y,
    title: "Pedido creado",
    subtitle: "order.confirm",
    icon: CheckCircle2,
  };
  const failureNode: GraphNode = {
    key: "n5b",
    cx: CENTERS.n5,
    cy: BRANCH_BOTTOM_Y,
    title: "Cierre sin pedido",
    subtitle: outcome && outcome !== "order.confirm" ? intentLabel(outcome) : "sin confirmar",
    icon: PhoneOff,
  };

  // Comprobante SUNAT y aviso de WhatsApp: pasan casi al toque de
  // confirmado el pedido, en paralelo, fuera del turno (ver
  // AgentRuntime._issue_invoice_and_notify) -- por eso van justo despues de
  // "Pedido creado" y ANTES del pipeline de cocina, no al final: cronologicamente
  // ya pasaron para cuando cocina siquiera se entera del pedido.
  const invoiceReached = Boolean(invoice);
  const invoiceCurrent = orderIsLive && !invoiceReached;
  const invoiceRejected = invoice?.sunat_status === "rejected";
  const whatsappReached = order?.whatsapp_status === "sent";
  const whatsappFailed = order?.whatsapp_status === "failed";
  const whatsappCurrent = orderIsLive && invoiceReached && !whatsappReached && !whatsappFailed;

  // Umbral de "reached" (checkmark) de cada nodo en la escala -1..2 de
  // fulfillmentStageIndex: Cocina esta reached en cuanto entra a preparar
  // (0+), Motorizado/Recojo en cuanto sale/esta listo (1+), Entregado solo
  // al llegar (2). "current" (glow activo) es el nodo que todavia no paso
  // ese umbral pero es el siguiente en la fila.
  const stageIdx = fulfillmentStageIndex;
  const kitchenReached = stageIdx !== null && stageIdx >= 0;
  const kitchenCurrent = orderIsLive && stageIdx === -1;
  const dispatchReached = stageIdx !== null && stageIdx >= 1;
  const dispatchCurrent = orderIsLive && stageIdx === 0;
  const deliveredReached = stageIdx !== null && stageIdx >= 2;

  const fulfillmentNodes: GraphNode[] = [
    {
      key: "n6",
      cx: CENTERS.n6,
      cy: BRANCH_TOP_Y,
      title: "Comprobante",
      subtitle: invoice
        ? `${invoiceDocumentLabel(invoice.document_type)} · ${sunatStatusLabel(invoice.sunat_status)}`
        : "emitiendo…",
      icon: Receipt,
    },
    {
      key: "n7",
      cx: CENTERS.n7,
      cy: BRANCH_TOP_Y,
      title: "WhatsApp",
      subtitle: whatsappStatusLabel(order?.whatsapp_status ?? null),
      icon: MessageCircle,
    },
    {
      key: "n8",
      cx: CENTERS.n8,
      cy: BRANCH_TOP_Y,
      title: "Cocina",
      subtitle: kitchenReached ? "aceptó el pedido" : "por aceptar",
      icon: ChefHat,
    },
    {
      key: "n9",
      cx: CENTERS.n9,
      cy: BRANCH_TOP_Y,
      title: isDelivery ? "Motorizado" : "Recojo en local",
      subtitle: isDelivery ? "salió a entregar" : "listo para recoger",
      icon: isDelivery ? Bike : Store,
    },
    {
      key: "n10",
      cx: CENTERS.n10,
      cy: BRANCH_TOP_Y,
      title: "Entregado",
      subtitle: "pedido cerrado",
      icon: PackageCheck,
    },
  ];
  // origin nodes de cada tramo: successNode -> comprobante -> whatsapp ->
  // cocina -> motorizado/recojo -> entregado. El "traveled" de cada tramo
  // es el "reached" del nodo al que llega; "flowing" es el tramo que lleva
  // al nodo que esta "current" en este momento (el siguiente sin resolver).
  const fulfillmentOrigins = [successNode, ...fulfillmentNodes];
  const fulfillmentReachedByTarget = [
    invoiceReached, whatsappReached || whatsappFailed, kitchenReached, dispatchReached, deliveredReached,
  ];
  const fulfillmentCurrentByTarget = [invoiceCurrent, whatsappCurrent, kitchenCurrent, dispatchCurrent, false];
  const fulfillmentEdges = [0, 1, 2, 3, 4].map((i) => {
    const from = fulfillmentOrigins[i]!;
    const to = fulfillmentOrigins[i + 1]!;
    const traveled = fulfillmentReachedByTarget[i]!;
    const flowing = orderIsLive && fulfillmentCurrentByTarget[i]!;
    return {
      key: `fedge-${i}`,
      d: `M${from.cx + HALF},${from.cy} L${to.cx - HALF},${to.cy}`,
      traveled,
      flowing,
    };
  });

  // i = indice del nodo de origen (0..2) -> conecta nodes[i] con nodes[i+1]
  const mainEdges = [0, 1, 2].map((i) => {
    const from = nodes[i]!;
    const to = nodes[i + 1]!;
    const traveled = i + 1 <= currentIndex;
    const flowing = isLive && i === currentIndex - 1;
    return {
      key: `edge-${i}`,
      d: `M${from.cx + HALF},${from.cy} L${to.cx - HALF},${to.cy}`,
      traveled,
      flowing,
    };
  });

  const toSuccess = `M${CENTERS.n4 + HALF},${ROW_Y} C ${CENTERS.n4 + 116},${ROW_Y} ${CENTERS.n5 - 116},${BRANCH_TOP_Y} ${CENTERS.n5 - HALF},${BRANCH_TOP_Y}`;
  const toFailure = `M${CENTERS.n4 + HALF},${ROW_Y} C ${CENTERS.n4 + 116},${ROW_Y} ${CENTERS.n5 - 116},${BRANCH_BOTTOM_Y} ${CENTERS.n5 - HALF},${BRANCH_BOTTOM_Y}`;
  const branchFlowing = isLive && currentIndex === 3;
  const viewW = showFulfillment ? VIEW_W_WITH_FULFILLMENT : VIEW_W;

  // El panel sigue "en vivo" mientras la llamada este abierta O el pedido
  // siga en curso (cocina/motorizado trabajando despues de colgar) -- ver
  // orderIsLive arriba.
  const panelIsLive = isLive || orderIsLive;

  return (
    <HudPanel className="overflow-hidden p-5" glow={panelIsLive}>
      {panelIsLive && (
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
            Cada nodo es una decision real del agente; la señal viaja por el conector activo mientras la llamada o el pedido siguen en curso.
          </p>
        </div>
        {panelIsLive ? (
          <span className="inline-flex items-center gap-1.5 rounded border border-hud-500/30 bg-hud-500/10 px-2.5 py-1.5 font-mono text-xs font-medium uppercase tracking-wide text-hud-300">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-hud-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-hud-400" />
            </span>
            {isLive ? "En vivo" : "Pedido en curso"}
          </span>
        ) : (
          <span className="rounded border border-surface-600 bg-surface-800 px-2.5 py-1.5 font-mono text-xs font-medium uppercase tracking-wide text-slate-500">
            Finalizada
          </span>
        )}
      </div>

      <div className="relative grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_310px]">
        <div className="relative overflow-x-auto rounded-lg border border-surface-800/80 bg-[radial-gradient(circle,rgba(77,216,240,0.06)_1px,transparent_1px)] bg-[length:22px_22px] pb-1">
          <div className="relative" style={{ width: viewW, height: VIEW_H }}>
            <svg
              viewBox={`0 0 ${viewW} ${VIEW_H}`}
              width={viewW}
              height={VIEW_H}
              className="absolute inset-0"
              aria-hidden
            >
              {mainEdges.map((edge) => (
                <g key={edge.key}>
                  <path
                    d={edge.d}
                    fill="none"
                    stroke={edge.traveled ? "#4dd8f0" : "#252b3b"}
                    strokeWidth={2.5}
                    strokeLinecap="round"
                    className={edge.flowing ? "hud-flow-edge-active" : ""}
                    opacity={edge.traveled ? 0.9 : 0.7}
                  />
                </g>
              ))}

              <path
                d={toSuccess}
                fill="none"
                stroke={successTaken ? "#2dd4bf" : "#252b3b"}
                strokeWidth={2.5}
                strokeLinecap="round"
                className={branchFlowing ? "hud-flow-edge-active" : ""}
                opacity={successTaken ? 0.95 : 0.55}
              />
              <path
                d={toFailure}
                fill="none"
                stroke={failureTaken ? "#f4667c" : "#252b3b"}
                strokeWidth={2.5}
                strokeLinecap="round"
                className={branchFlowing ? "hud-flow-edge-active" : ""}
                opacity={failureTaken ? 0.95 : 0.55}
              />

              {/* puertos: puntito en cada extremo de cada conector, como en n8n */}
              {mainEdges.map((edge, i) => (
                <g key={`ports-${edge.key}`}>
                  <circle cx={nodes[i]!.cx + HALF} cy={nodes[i]!.cy} r={3} fill={edge.traveled ? "#4dd8f0" : "#343c52"} />
                  <circle
                    cx={nodes[i + 1]!.cx - HALF}
                    cy={nodes[i + 1]!.cy}
                    r={3}
                    fill={edge.traveled ? "#4dd8f0" : "#343c52"}
                  />
                </g>
              ))}
              <circle cx={CENTERS.n4 + HALF} cy={ROW_Y} r={3} fill="#4dd8f0" />
              <circle cx={CENTERS.n5 - HALF} cy={BRANCH_TOP_Y} r={3} fill={successTaken ? "#2dd4bf" : "#343c52"} />
              <circle cx={CENTERS.n5 - HALF} cy={BRANCH_BOTTOM_Y} r={3} fill={failureTaken ? "#f4667c" : "#343c52"} />

              {showFulfillment &&
                fulfillmentEdges.map((edge, i) => (
                  <g key={edge.key}>
                    <path
                      d={edge.d}
                      fill="none"
                      stroke={edge.traveled ? "#2dd4bf" : "#252b3b"}
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      className={edge.flowing ? "hud-flow-edge-active" : ""}
                      opacity={edge.traveled ? 0.9 : 0.7}
                    />
                    <circle
                      cx={fulfillmentOrigins[i]!.cx + HALF}
                      cy={fulfillmentOrigins[i]!.cy}
                      r={3}
                      fill={edge.traveled ? "#2dd4bf" : "#343c52"}
                    />
                    <circle
                      cx={fulfillmentOrigins[i + 1]!.cx - HALF}
                      cy={fulfillmentOrigins[i + 1]!.cy}
                      r={3}
                      fill={edge.traveled ? "#2dd4bf" : "#343c52"}
                    />
                  </g>
                ))}

              <text
                x={(CENTERS.n4 + CENTERS.n5) / 2 + 10}
                y={BRANCH_TOP_Y - 12}
                textAnchor="middle"
                className="font-mono"
                fontSize={10}
                fill={successTaken ? "#2dd4bf" : "#5b6478"}
                letterSpacing={1.5}
              >
                SÍ
              </text>
              <text
                x={(CENTERS.n4 + CENTERS.n5) / 2 + 10}
                y={BRANCH_BOTTOM_Y + 20}
                textAnchor="middle"
                className="font-mono"
                fontSize={10}
                fill={failureTaken ? "#f4667c" : "#5b6478"}
                letterSpacing={1.5}
              >
                NO
              </text>
            </svg>

            {nodes.map((node, index) => (
              <FlowNodeCard
                key={node.key}
                node={node}
                reached={index <= currentIndex}
                current={index === currentIndex && !isEnded && isLive}
              />
            ))}
            <FlowNodeCard node={successNode} reached={successTaken} current={false} tone="success" dim={finalReached && !successTaken} />
            <FlowNodeCard node={failureNode} reached={failureTaken} current={false} tone="failure" dim={finalReached && !failureTaken} />

            {showFulfillment && (
              <>
                <FlowNodeCard
                  node={fulfillmentNodes[0]!}
                  reached={invoiceReached}
                  current={invoiceCurrent}
                  tone={invoiceRejected ? "failure" : "hud"}
                />
                <FlowNodeCard
                  node={fulfillmentNodes[1]!}
                  reached={whatsappReached || whatsappFailed}
                  current={whatsappCurrent}
                  tone={whatsappFailed ? "failure" : "hud"}
                />
                <FlowNodeCard node={fulfillmentNodes[2]!} reached={kitchenReached} current={kitchenCurrent} />
                <FlowNodeCard node={fulfillmentNodes[3]!} reached={dispatchReached} current={dispatchCurrent} />
                <FlowNodeCard
                  node={fulfillmentNodes[4]!}
                  reached={deliveredReached}
                  current={false}
                  tone="success"
                />
              </>
            )}
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

          {order && order.items.length > 0 && (
            <div className="mt-4 border-t border-surface-700 pt-4">
              <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-500">Se pidió</p>
              <ul className="mt-3 space-y-1 text-sm text-slate-300">
                {order.items.map((item, idx) => (
                  <li key={idx} className="flex items-baseline justify-between gap-2">
                    <span className="truncate">
                      <span className="font-semibold text-white">{item.quantity}×</span> {item.product_name}
                    </span>
                    <span className="shrink-0 font-mono text-xs text-slate-500">
                      {formatCurrency(item.unit_price * item.quantity)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {showFulfillment && (
            <div className="mt-4 border-t border-surface-700 pt-4">
              <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-500">
                Comprobante y aviso
              </p>
              <div className="mt-3 space-y-2">
                <div
                  className={[
                    "flex items-center justify-between gap-2 border px-2.5 py-2 text-xs",
                    invoiceRejected
                      ? "border-accent-rose/30 bg-accent-rose/5 text-accent-rose"
                      : invoiceReached
                        ? "border-accent-teal/25 bg-accent-teal/5 text-slate-300"
                        : "border-hud-400/40 bg-hud-500/10 text-hud-300",
                  ].join(" ")}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    <Receipt size={13} className="shrink-0" />
                    <span className="truncate">
                      {invoice
                        ? `${invoiceDocumentLabel(invoice.document_type)} ${invoice.serie}-${String(invoice.numero).padStart(3, "0")}`
                        : "Emitiendo comprobante…"}
                    </span>
                  </span>
                  {invoice?.sunat_pdf_a4_url ? (
                    <a
                      href={invoice.sunat_pdf_a4_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 font-medium text-hud-300 underline decoration-dotted underline-offset-2 hover:text-hud-200"
                    >
                      Ver PDF
                    </a>
                  ) : (
                    <span className="shrink-0 font-mono uppercase tracking-wide">
                      {invoice ? sunatStatusLabel(invoice.sunat_status) : "…"}
                    </span>
                  )}
                </div>
                {invoice?.cliente_numero_doc && (
                  <p className="px-0.5 text-xs text-slate-500">
                    {invoice.document_type === "factura" ? "RUC" : "DNI"}: {invoice.cliente_numero_doc}
                    {invoice.cliente_denominacion ? ` · ${invoice.cliente_denominacion}` : ""}
                  </p>
                )}

                <div
                  className={[
                    "flex items-center gap-2 border px-2.5 py-2 text-xs",
                    whatsappFailed
                      ? "border-accent-rose/30 bg-accent-rose/5 text-accent-rose"
                      : whatsappReached
                        ? "border-accent-teal/25 bg-accent-teal/5 text-slate-300"
                        : "border-hud-400/40 bg-hud-500/10 text-hud-300",
                  ].join(" ")}
                >
                  <MessageCircle size={13} className="shrink-0" />
                  <span className="flex-1 truncate">
                    Mensaje al WhatsApp{order?.customer_id ? "" : " del cliente"}: {whatsappStatusLabel(order?.whatsapp_status ?? null)}
                  </span>
                  {whatsappReached && <CheckCircle2 size={13} className="shrink-0 text-accent-teal" />}
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>
    </HudPanel>
  );
}

function FlowNodeCard({
  node,
  reached,
  current,
  tone = "hud",
  dim = false,
}: {
  node: GraphNode;
  reached: boolean;
  current: boolean;
  tone?: "hud" | "success" | "failure";
  dim?: boolean;
}) {
  const Icon = node.icon;
  const toneClasses = dim
    ? "border-surface-700 bg-surface-900/70 text-slate-600"
    : tone === "success"
      ? "border-accent-teal/60 bg-accent-teal/10 text-accent-teal shadow-[0_0_20px_-6px_rgba(45,212,191,0.55)]"
      : tone === "failure"
        ? "border-accent-rose/60 bg-accent-rose/10 text-accent-rose shadow-[0_0_20px_-6px_rgba(244,102,124,0.5)]"
        : current
          ? "border-hud-400/70 bg-hud-500/15 text-hud-300 shadow-hud"
          : reached
            ? "border-hud-500/40 bg-hud-500/10 text-hud-400"
            : "border-surface-700 bg-surface-900/70 text-slate-600";

  const labelWidth = 150;

  return (
    <div
      className="absolute flex flex-col items-center"
      style={{ left: node.cx - labelWidth / 2, top: node.cy - HALF, width: labelWidth }}
    >
      <div
        className={`relative flex items-center justify-center rounded-2xl border transition-all duration-500 ${toneClasses}`}
        style={{ width: NODE, height: NODE }}
      >
        {current && <span className="hud-scanline absolute inset-0 rounded-2xl" aria-hidden />}
        <Icon size={26} className={current ? "animate-pulse-slow" : ""} />
        {reached && !dim && (
          <span className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full border border-surface-950 bg-accent-teal text-surface-950">
            <CheckCircle2 size={11} strokeWidth={3} />
          </span>
        )}
      </div>
      <p className={`mt-2 max-w-[150px] truncate text-center text-xs font-semibold ${dim ? "text-slate-600" : "text-white"}`}>
        {node.title}
      </p>
      <p className="max-w-[150px] truncate text-center font-mono text-[10px] uppercase tracking-wide text-slate-600">
        {node.subtitle}
      </p>
    </div>
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
