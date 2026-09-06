"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ROLE_HOME, SESSION_COOKIE, canAccess, checkCredentials, createSessionToken } from "@/lib/auth";

export interface LoginState {
  error?: string;
}

export async function loginAction(_prevState: LoginState, formData: FormData): Promise<LoginState> {
  const username = String(formData.get("username") ?? "");
  const password = String(formData.get("password") ?? "");
  const next = String(formData.get("next") ?? "");

  const role = checkCredentials(username, password);
  if (!role) return { error: "Usuario o contraseña incorrectos." };

  const token = await createSessionToken(role);
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });

  // "next" viene del ?next= que puso el middleware al mandar a alguien sin
  // sesion a /login (ver middleware.ts) -- solo se respeta si el rol que
  // acaba de entrar realmente tiene acceso a esa ruta, si no, a su pantalla
  // de siempre.
  const destination = next.startsWith("/") && canAccess(role, next) ? next : ROLE_HOME[role];
  redirect(destination);
}

export async function logoutAction(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE);
  redirect("/login");
}
