import { ExternalLink, FileText, Landmark, Receipt } from "lucide-react";
import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { Pill } from "@/components/Badge";
import { HudPanel } from "@/components/HudPanel";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { BarList } from "@/features/analytics/BarList";
import { parseAnalyticsRange, RangePicker } from "@/features/analytics/RangePicker";
import { ApiError, api } from "@/lib/api";
import { formatCurrency, invoiceDocumentLabel, sunatStatusLabel } from "@/lib/format";
import type { SunatStatus } from "@/lib/types";

export const metadata: Metadata = { title: "Contabilidad · Comprobantes" };

const STATUS_TONE: Record<string, "neutral" | "success" | "danger" | "info"> = {
  draft: "neutral",
  sent: "info",
  pending: "info",
  accepted: "success",
  rejected: "danger",
  voided: "danger",
};

export default async function ContabilidadComprobantesPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const range = parseAnalyticsRange((await searchParams).range);

  try {
    const report = await api.analytics.invoices(range, 200);

    return (
      <div>
        <PageHeader
          title="Comprobantes"
          description="Boletas y facturas electrónicas emitidas ante SUNAT (apisunat.pe) -- serie, estado y el PDF real de cada una."
        />
        <RangePicker basePath="/contabilidad/comprobantes" active={range} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard label="Comprobantes emitidos" value={String(report.invoices_count)} icon={Receipt} accent="hud" />
          <StatCard
            label="Facturado (aceptado por SUNAT)"
            value={formatCurrency(report.total_facturado_aceptado)}
            icon={Landmark}
            accent="teal"
          />
          <StatCard label="IGV recaudado" value={formatCurrency(report.total_igv_aceptado)} icon={FileText} accent="amber" />
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <HudPanel className="p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-200">Por tipo de comprobante</h2>
            <BarList
              rows={report.by_document_type.map((t) => ({
                label: invoiceDocumentLabel(t.document_type),
                value: t.total,
                secondary: `${t.count} emitido${t.count === 1 ? "" : "s"}`,
              }))}
              formatValue={formatCurrency}
              accent="teal"
            />
            <p className="mt-3 text-xs text-slate-500">Solo comprobantes aceptados por SUNAT.</p>
          </HudPanel>

          <HudPanel className="p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-200">Por estado SUNAT</h2>
            <BarList
              rows={report.by_status.map((s) => ({
                label: sunatStatusLabel(s.status),
                value: s.total,
                secondary: `${s.count} comprobante${s.count === 1 ? "" : "s"}`,
              }))}
              formatValue={formatCurrency}
              accent="amber"
            />
          </HudPanel>
        </div>

        <HudPanel className="mt-6 overflow-hidden p-0">
          <div className="p-5 pb-0">
            <h2 className="text-sm font-semibold text-slate-200">Detalle de comprobantes</h2>
          </div>
          {report.recent_invoices.length === 0 ? (
            <p className="p-5 text-sm text-slate-500">Sin comprobantes en este período.</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-surface-700 text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-5 py-2 font-medium">Serie</th>
                    <th className="px-3 py-2 font-medium">Tipo</th>
                    <th className="px-3 py-2 font-medium">Fecha</th>
                    <th className="px-3 py-2 font-medium">Cliente</th>
                    <th className="px-3 py-2 text-right font-medium">Total</th>
                    <th className="px-3 py-2 font-medium">Estado</th>
                    <th className="px-5 py-2 font-medium">PDF</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-800">
                  {report.recent_invoices.map((inv) => (
                    <tr key={inv.id}>
                      <td className="px-5 py-2 font-mono text-xs text-slate-300">{inv.serie_numero}</td>
                      <td className="px-3 py-2 text-slate-400">{invoiceDocumentLabel(inv.document_type)}</td>
                      <td className="px-3 py-2 text-slate-400">{inv.fecha_emision}</td>
                      <td className="px-3 py-2 text-slate-300">{inv.cliente_denominacion}</td>
                      <td className="px-3 py-2 text-right font-medium text-slate-200">{formatCurrency(inv.total)}</td>
                      <td className="px-3 py-2">
                        <Pill tone={STATUS_TONE[inv.sunat_status as SunatStatus] ?? "neutral"}>
                          {sunatStatusLabel(inv.sunat_status)}
                        </Pill>
                      </td>
                      <td className="px-5 py-2">
                        {inv.pdf_a4_url ? (
                          <a
                            href={inv.pdf_a4_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs font-medium text-hud-400 hover:underline"
                          >
                            Ver PDF <ExternalLink size={12} />
                          </a>
                        ) : (
                          <span className="text-xs text-slate-600">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </HudPanel>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Comprobantes" />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
