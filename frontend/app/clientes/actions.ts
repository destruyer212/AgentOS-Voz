"use server";

import { revalidatePath } from "next/cache";
import { ApiError, api } from "@/lib/api";

export interface CreateCustomerState {
  error?: string;
  success?: boolean;
}

export async function createCustomerAction(
  _prevState: CreateCustomerState,
  formData: FormData,
): Promise<CreateCustomerState> {
  const name = String(formData.get("name") ?? "").trim();
  const phone = String(formData.get("phone") ?? "").trim();
  const address = String(formData.get("address") ?? "").trim();
  const notes = String(formData.get("notes") ?? "").trim();

  if (!name) {
    return { error: "El nombre es obligatorio." };
  }

  try {
    await api.customers.create({
      name,
      phone: phone || undefined,
      address: address || undefined,
      notes: notes || undefined,
    });
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error inesperado al crear el cliente.";
    return { error: message };
  }

  revalidatePath("/clientes");
  return { success: true };
}
