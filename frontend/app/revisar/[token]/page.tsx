import { CheckCircle2, Clock, PhoneCall, ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import { LiveRefresher } from "@/components/LiveRefresher";
import { ApiError, api } from "@/lib/api";
import { formatCurrency, fulfillmentLabel, invoiceDocumentLabel, paymentMethodLabel } from "@/lib/format";
import type { OrderReview } from "@/lib/types";

// Carrito visual durante la llamada (ver
// docs/08-mejora-carrito-visual-en-llamada.md) -- pagina publica, SIN
// login: el cliente la abre desde el link que le mandamos por WhatsApp
// mientras sigue en la llamada. Por eso vive fuera del layout con menu de
// admin (ver app/layout.tsx: sin cookie de sesion, se renderiza sola) y
// middleware.ts la deja pasar sin pedir cookie. Nunca pide confirmar/
// cancelar desde aca -- eso sigue siendo por voz, esto es solo un espejo
// en vivo para que el cliente revise antes de decir "sí" por telefono.
export const metadata: Metadata = { title: "Tu pedido" };

function statusLabel(review: OrderReview): string {
  if (review.awaiting_confirmation) return "Esperando que confirmes por teléfono";
  if (review.closed) return "Esta conversación ya terminó";
  return "Armando tu pedido todavía...";
}

export default async function OrderReviewPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;

  let review: OrderReview;
  try {
    review = await api.orderReview.get(token);
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div className="flex min-h-screen items-center justify-center px-4 text-center">
        <div className="max-w-sm">
          <p className="text-lg font-semibold text-white">No pudimos abrir tu pedido</p>
          <p className="mt-2 text-sm text-slate-400">{message}</p>
          <p className="mt-4 text-xs text-slate-500">
            Si sigues en la llamada, dile al agente que necesitas el link de nuevo.
          </p>
        </div>
      </div>
    );
  }

  const hasDocument = review.boleta_dni || review.factura_ruc;

  return (
    <div className="min-h-screen px-4 py-8">
      <LiveRefresher active={!review.closed} intervalMs={3000} />
      <div className="mx-auto max-w-md">
        <div className="mb-6 flex items-center gap-2 text-hud-400">
          <PhoneCall size={18} />
          <p className="font-mono text-xs uppercase tracking-[0.18em]">El Olivar Grill · En llamada</p>
        </div>

        <div
          className={`mb-5 flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-medium ${
            review.awaiting_confirmation
              ? "border-accent-teal/35 bg-accent-teal/10 text-accent-teal"
              : review.closed
                ? "border-surface-700 bg-surface-800 text-slate-400"
                : "border-accent-amber/35 bg-accent-amber/10 text-accent-amber"
          }`}
        >
          {review.awaiting_confirmation ? <CheckCircle2 size={16} /> : <Clock size={16} />}
          {statusLabel(review)}
        </div>

        <div className="rounded-xl border border-surface-700 bg-surface-900 p-5">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-slate-500">
            {review.customer_name ? `Pedido de ${review.customer_name}` : "Tu pedido"}
          </p>

          {review.items.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500">Todavía no hay productos en tu pedido.</p>
          ) : (
            <ul className="space-y-2">
              {review.items.map((item, idx) => (
                <li key={idx} className="flex items-start justify-between gap-3 text-sm">
                  <span className="text-slate-200">
                    <span className="font-medium text-white">{item.quantity}×</span> {item.name}
                    {item.notes && <span className="text-slate-500"> · {item.notes}</span>}
                  </span>
                  <span className="shrink-0 font-mono text-xs text-slate-400">
                    {formatCurrency(item.unit_price * item.quantity)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4 space-y-1 border-t border-surface-800 pt-4 text-sm">
            <div className="flex justify-between text-slate-400">
              <span>Subtotal</span>
              <span>{formatCurrency(review.subtotal)}</span>
            </div>
            {review.delivery_fee > 0 && (
              <div className="flex justify-between text-slate-400">
                <span>Delivery</span>
                <span>{formatCurrency(review.delivery_fee)}</span>
              </div>
            )}
            <div className="flex justify-between pt-1 text-base font-semibold text-white">
              <span>Total</span>
              <span>{formatCurrency(review.total)}</span>
            </div>
          </div>
        </div>

        <div className="mt-4 space-y-2 rounded-xl border border-surface-700 bg-surface-900 p-5 text-sm">
          {review.fulfillment_type && (
            <p className="flex justify-between">
              <span className="text-slate-500">Entrega</span>
              <span className="text-right text-slate-200">
                {fulfillmentLabel(review.fulfillment_type)}
                {review.delivery_address && ` · ${review.delivery_address}`}
              </span>
            </p>
          )}
          {review.payment_method && (
            <p className="flex justify-between">
              <span className="text-slate-500">Pago</span>
              <span className="text-slate-200">{paymentMethodLabel(review.payment_method)}</span>
            </p>
          )}
          {review.invoice_document_type && (
            <p className="flex justify-between">
              <span className="text-slate-500">Comprobante</span>
              <span className="text-right text-slate-200">
                {invoiceDocumentLabel(review.invoice_document_type)}
                {review.boleta_dni && ` · DNI ${review.boleta_dni}`}
                {review.factura_ruc && ` · RUC ${review.factura_ruc}`}
              </span>
            </p>
          )}
          {hasDocument && (review.boleta_dni_name || review.factura_razon_social) && (
            <p className="flex justify-between">
              <span className="text-slate-500">A nombre de</span>
              <span className="text-right text-slate-200">
                {review.boleta_dni_name || review.factura_razon_social}
              </span>
            </p>
          )}
        </div>

        <p className="mt-5 flex items-start gap-2 text-xs text-slate-500">
          <ShieldCheck size={14} className="mt-0.5 shrink-0" />
          Si algo está mal, dilo por teléfono -- el agente lo corrige ahí mismo. Esta página se actualiza sola
          mientras sigues en la llamada.
        </p>
      </div>
    </div>
  );
}
