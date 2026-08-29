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

export interface UpdateCustomerState {
  error?: string;
  success?: boolean;
}

export async function updateCustomerAction(
  _prevState: UpdateCustomerState,
  formData: FormData,
): Promise<UpdateCustomerState> {
  const id = Number(formData.get("id"));
  const name = String(formData.get("name") ?? "").trim();
  const phone = String(formData.get("phone") ?? "").trim();
  const address = String(formData.get("address") ?? "").trim();
  const notes = String(formData.get("notes") ?? "").trim();

  if (!id) return { error: "Cliente inválido." };
  if (!name) return { error: "El nombre es obligatorio." };

  try {
    await api.customers.update(id, {
      name,
      phone: phone || null,
      address: address || null,
      notes: notes || null,
    });
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error inesperado al editar el cliente.";
    return { error: message };
  }

  revalidatePath("/clientes");
  return { success: true };
}

export interface DeleteCustomerState {
  error?: string;
  success?: boolean;
}

export async function deleteCustomerAction(
  _prevState: DeleteCustomerState,
  formData: FormData,
): Promise<DeleteCustomerState> {
  const id = Number(formData.get("id"));
  if (!id) return { error: "Cliente inválido." };

  try {
    await api.customers.remove(id);
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error inesperado al eliminar el cliente.";
    return { error: message };
  }

  revalidatePath("/clientes");
  return { success: true };
}
