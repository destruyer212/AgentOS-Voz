import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { ProductsTable } from "@/features/products/ProductsTable";
import { ApiError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Productos" };

export default async function ProductosPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;

  try {
    const products = await api.products.list(q);
    return (
      <div>
        <PageHeader
          title="Productos"
          description="Catálogo y stock disponible. El agente busca aquí con matching difuso."
          action={<SearchInput placeholder="Buscar producto..." />}
        />
        <ProductsTable products={products} />
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Productos" action={<SearchInput placeholder="Buscar producto..." />} />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
