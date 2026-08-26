"use client";

import { UserPlus } from "lucide-react";
import { useActionState, useEffect, useRef } from "react";
import { createCustomerAction, type CreateCustomerState } from "@/app/clientes/actions";

const initialState: CreateCustomerState = {};

export function NewCustomerForm() {
  const [state, formAction, isPending] = useActionState(createCustomerAction, initialState);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state.success) {
      formRef.current?.reset();
    }
  }, [state.success]);

  return (
    <form ref={formRef} action={formAction} className="rounded-xl border border-surface-700 bg-surface-900 p-5">
      <div className="mb-4 flex items-center gap-2">
        <UserPlus size={16} className="text-brand-400" />
        <h2 className="text-sm font-semibold text-slate-200">Nuevo cliente</h2>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <input name="name" placeholder="Nombre *" required className="form-input" />
        <input name="phone" placeholder="Teléfono" className="form-input" />
        <input name="address" placeholder="Dirección" className="form-input sm:col-span-2" />
        <input name="notes" placeholder="Notas" className="form-input sm:col-span-2" />
      </div>
      {state.error && <p className="mt-3 text-sm text-accent-rose">{state.error}</p>}
      {state.success && <p className="mt-3 text-sm text-accent-teal">Cliente agregado.</p>}
      <button type="submit" disabled={isPending} className="btn-primary mt-4">
        {isPending ? "Guardando…" : "Agregar cliente"}
      </button>
    </form>
  );
}
