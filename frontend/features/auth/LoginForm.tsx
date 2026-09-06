"use client";

import { LogIn } from "lucide-react";
import { useActionState } from "react";
import { loginAction, type LoginState } from "@/app/login/actions";

const initialState: LoginState = {};

export function LoginForm({ next }: { next: string }) {
  const [state, formAction, isPending] = useActionState(loginAction, initialState);

  return (
    <form action={formAction} className="flex flex-col gap-4">
      <input type="hidden" name="next" value={next} />
      <div>
        <label htmlFor="username" className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
          Usuario
        </label>
        <input
          id="username"
          name="username"
          autoComplete="username"
          required
          autoFocus
          className="form-input"
          placeholder="admin / cocina / recepcion"
        />
      </div>
      <div>
        <label htmlFor="password" className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
          Contraseña
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className="form-input"
        />
      </div>
      {state.error && <p className="text-sm text-accent-rose">{state.error}</p>}
      <button type="submit" disabled={isPending} className="btn-primary mt-1 justify-center">
        <LogIn size={16} />
        {isPending ? "Entrando…" : "Entrar"}
      </button>
    </form>
  );
}
