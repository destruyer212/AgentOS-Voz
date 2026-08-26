import { UtensilsCrossed } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Badge";
import { formatCurrency } from "@/lib/format";
import type { ProductOut } from "@/lib/types";

export function ProductsTable({ products }: { products: ProductOut[] }) {
  if (products.length === 0) {
    return (
      <EmptyState
        icon={UtensilsCrossed}
        title="Sin resultados"
        description="No encontramos productos que coincidan con esa búsqueda."
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {products.map((product) => {
        const lowStock = product.stock_available <= 10;
        return (
          <div
            key={product.id}
            className="flex flex-col rounded-xl border border-surface-700 bg-surface-900 p-4 shadow-panel"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="font-medium text-slate-100">{product.name}</p>
              <Pill tone={lowStock ? "danger" : "success"}>{product.stock_available} en stock</Pill>
            </div>
            {product.description && (
              <p className="mt-1.5 line-clamp-2 text-sm text-slate-500">{product.description}</p>
            )}
            <div className="mt-auto flex items-center justify-between pt-4">
              <span className="font-mono text-xs text-slate-500">{product.sku}</span>
              <span className="text-lg font-semibold text-white">{formatCurrency(product.price)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
