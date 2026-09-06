// Parte de lib/auth.ts que es segura para importar desde un componente
// cliente (Sidebar necesita el tipo Role y las etiquetas para pintar el
// menu) -- sin contraseñas, sin firma de cookies. Todo lo que toca
// secretos (checkCredentials, createSessionToken, verifySessionToken) vive
// en lib/auth.ts, protegido con "server-only", precisamente para que no se
// puede repetir el error de terminar empaquetando los defaults de
// contraseña en el bundle del navegador.

export type Role = "admin" | "cocina" | "recepcion";

export const ROLE_HOME: Record<Role, string> = {
  admin: "/",
  cocina: "/cocina",
  recepcion: "/recepcion",
};

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Administrador",
  cocina: "Cocina",
  recepcion: "Recepción",
};

export const SESSION_COOKIE = "aos_session";

// A que rutas puede entrar cada rol -- admin ve todo (incluidas /cocina y
// /recepcion), cocina y recepcion solo su propia area. Ver middleware.ts.
export function canAccess(role: Role, pathname: string): boolean {
  if (role === "admin") return true;
  if (role === "cocina") return pathname === "/cocina" || pathname.startsWith("/cocina/");
  if (role === "recepcion") return pathname === "/recepcion" || pathname.startsWith("/recepcion/");
  return false;
}
