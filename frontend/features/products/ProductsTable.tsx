"use client";

import { UtensilsCrossed } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Badge";
import { categoryLabel, formatCurrency } from "@/lib/format";
import type { ProductOut } from "@/lib/types";

export function ProductsTable({ products }: { products: ProductOut[] }) {
  const categories = useMemo(() => {
    const set = new Set(products.map((p) => p.category));
    return Array.from(set).sort((a, b) => categoryLabel(a).localeCompare(categoryLabel(b)));
  }, [products]);
  const [active, setActive] = useState<string | null>(null);

  if (products.length === 0) {
    return (
      <EmptyState
        icon={UtensilsCrossed}
        title="Sin resultados"
        description="No encontramos productos que coincidan con esa búsqueda."
      />
    );
  }

  const visible = active ? products.filter((p) => p.category === active) : products;
  const grouped = active
    ? [{ category: active, items: visible }]
    : categories.map((category) => ({ category, items: products.filter((p) => p.category === category) }));

  return (
    <div>
      <div className="mb-5 flex flex-wrap gap-2">
        <CategoryPill label={`Todas (${products.length})`} isActive={active === null} onClick={() => setActive(null)} />
        {categories.map((category) => {
          const count = products.filter((p) => p.category === category).length;
          return (
            <CategoryPill
              key={category}
              label={`${categoryLabel(category)} (${count})`}
              isActive={active === category}
              onClick={() => setActive(category)}
            />
          );
        })}
      </div>

      <div className="space-y-8">
        {grouped.map(({ category, items }) => (
          <section key={category}>
            <div className="mb-3 flex items-center gap-2">
              <span className="h-1 w-1 rounded-full bg-hud-400" />
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {categoryLabel(category)}
              </h2>
              <span className="text-xs text-slate-600">{items.length}</span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((product) => (
                <ProductCard key={product.id} product={product} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function CategoryPill({
  label,
  isActive,
  onClick,
}: {
  label: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
        isActive
          ? "border-hud-500/50 bg-hud-500/15 text-hud-400"
          : "border-surface-700 bg-surface-800 text-slate-400 hover:border-surface-600 hover:text-slate-200"
      }`}
    >
      {label}
    </button>
  );
}

function ProductCard({ product }: { product: ProductOut }) {
  const lowStock = product.stock_available <= 10;
  return (
    <div className="group relative flex flex-col overflow-hidden rounded-xl border border-surface-700 bg-surface-900 p-4 shadow-panel transition-colors hover:border-hud-500/30">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-hud-400/0 to-transparent transition-all duration-500 group-hover:via-hud-400/60" />
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
}
