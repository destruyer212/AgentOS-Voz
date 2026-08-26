import type { Metadata } from "next";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { CustomersTable } from "@/features/customers/CustomersTable";
import { NewCustomerForm } from "@/features/customers/NewCustomerForm";
import { ApiError, api } from "@/lib/api";

export const metadata: Metadata = { title: "Clientes" };

export default async function ClientesPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;

  try {
    const customers = await api.customers.list(q);
    return (
      <div>
        <PageHeader
          title="Clientes"
          description={`${customers.length} cliente${customers.length === 1 ? "" : "s"} registrados`}
          action={<SearchInput placeholder="Buscar por nombre o teléfono..." />}
        />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <CustomersTable customers={customers} />
          </div>
          <NewCustomerForm />
        </div>
      </div>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error desconocido.";
    return (
      <div>
        <PageHeader title="Clientes" action={<SearchInput placeholder="Buscar por nombre o teléfono..." />} />
        <ApiErrorNotice message={message} />
      </div>
    );
  }
}
