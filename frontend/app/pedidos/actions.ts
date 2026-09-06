"use server";

import { revalidatePath } from "next/cache";
import { ApiError, api } from "@/lib/api";

export interface UpdateOrderStatusState {
  error?: string;
  success?: boolean;
}

export async function updateOrderStatusAction(
  _prevState: UpdateOrderStatusState,
  formData: FormData,
): Promise<UpdateOrderStatusState> {
  const id = Number(formData.get("id"));
  const status = String(formData.get("status") ?? "");
  if (!id || !status) return { error: "Datos inválidos." };

  try {
    await api.orders.updateStatus(id, status);
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Error inesperado al cambiar el estado.";
    return { error: message };
  }

  // Un mismo pedido puede cambiar de estado desde 3 pantallas distintas
  // (admin en /pedidos, cocina, recepcion) -- revalidar las 3 asi la que
  // no disparo la accion tambien se refresca al toque, sin esperar al
  // siguiente tick de LiveRefresher.
  revalidatePath("/pedidos");
  revalidatePath("/cocina");
  revalidatePath("/recepcion");
  revalidatePath("/");
  return { success: true };
}
