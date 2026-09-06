import "server-only";

// Login del panel: 3 roles fijos (admin, cocina, recepcion), sin tabla de
// usuarios en la base de datos -- es intencional, el personal del local no
// da de alta gente nueva seguido y "facil de recordar" pesa mas que un
// sistema de usuarios completo. Las credenciales reales de produccion se
// configuran por variable de entorno (Vercel); los valores por defecto de
// aca abajo son SOLO para que `npm run dev` funcione sin configurar nada.
//
// "server-only" arriba es a proposito: este archivo tiene las contraseñas
// por defecto y la firma de la cookie de sesion, nunca debe poder terminar
// en el bundle del navegador. Lo unico seguro para un componente cliente
// (el tipo Role, las etiquetas, SESSION_COOKIE, canAccess) vive aparte en
// ./auth-shared -- ver Sidebar.tsx.
//
// Se usa tanto desde middleware.ts (Edge runtime) como desde Server
// Actions/Server Components (Node) -- por eso firma con Web Crypto
// (`crypto.subtle`), que existe en los dos entornos, en vez del modulo
// "crypto" de Node.

import type { Role } from "./auth-shared";

export type { Role };
export { ROLE_HOME, ROLE_LABEL, SESSION_COOKIE, canAccess } from "./auth-shared";

// 30 dias: uso interno de un solo local, no tiene sentido pedir login todo
// el rato en una tablet que se queda prendida en el mostrador.
const SESSION_TTL_MS = 1000 * 60 * 60 * 24 * 30;

function getSecret(): string {
  return process.env.AUTH_SECRET || "dev-secret-agentos-voz-cambiar-en-produccion";
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function hmac(data: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(getSecret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data));
  return base64UrlEncode(new Uint8Array(signature));
}

function isRole(value: string | undefined): value is Role {
  return value === "admin" || value === "cocina" || value === "recepcion";
}

// Token = "<rol>.<vence_en_ms>.<firma>" -- sin JSON, sin libreria de JWT:
// es lo minimo que hace falta para 3 roles fijos, firmado para que nadie
// pueda escribirse la cookie a mano y entrar como admin.
export async function createSessionToken(role: Role): Promise<string> {
  const payload = `${role}.${Date.now() + SESSION_TTL_MS}`;
  const signature = await hmac(payload);
  return `${payload}.${signature}`;
}

export async function verifySessionToken(token: string | undefined | null): Promise<Role | null> {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [role, expiresAtRaw, signature] = parts;
  const expected = await hmac(`${role}.${expiresAtRaw}`);
  if (expected !== signature) return null;
  const expiresAt = Number(expiresAtRaw);
  if (!Number.isFinite(expiresAt) || Date.now() > expiresAt) return null;
  if (!isRole(role)) return null;
  return role;
}

interface RoleCredentials {
  role: Role;
  user: string;
  pass: string;
}

// Defaults pensados para que el personal los recuerde sin anotarlos --
// usuario = el nombre del area, clave = el area + un año. En produccion se
// pisan con AUTH_*_USER / AUTH_*_PASS en las variables de entorno de
// Vercel (ver frontend/README.md).
function roleCredentials(): RoleCredentials[] {
  return [
    { role: "admin", user: process.env.AUTH_ADMIN_USER || "admin", pass: process.env.AUTH_ADMIN_PASS || "Olivar2024" },
    { role: "cocina", user: process.env.AUTH_COCINA_USER || "cocina", pass: process.env.AUTH_COCINA_PASS || "Cocina2024" },
    {
      role: "recepcion",
      user: process.env.AUTH_RECEPCION_USER || "recepcion",
      pass: process.env.AUTH_RECEPCION_PASS || "Recepcion2024",
    },
  ];
}

export function checkCredentials(username: string, password: string): Role | null {
  const normalized = username.trim().toLowerCase();
  const match = roleCredentials().find((c) => c.user.toLowerCase() === normalized && c.pass === password);
  return match?.role ?? null;
}
