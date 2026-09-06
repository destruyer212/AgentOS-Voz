import { NextResponse, type NextRequest } from "next/server";
import { ROLE_HOME, SESSION_COOKIE, canAccess, verifySessionToken } from "@/lib/auth";

// Gate de login para las 3 pantallas del panel (ver lib/auth.ts): sin
// cookie de sesion valida, todo redirige a /login. Con sesion valida pero
// del rol equivocado (ej. cocina tratando de entrar a /pedidos), redirige a
// la pantalla propia de ese rol en vez de mostrar un 403 pelado.
export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const role = await verifySessionToken(token);

  if (pathname === "/login") {
    // Ya logueado y tratando de volver a /login: mandarlo derecho a su
    // pantalla, asi el layout raiz nunca tiene que decidir si mostrar el
    // login con el menu alrededor o no (ver app/layout.tsx).
    if (role) return NextResponse.redirect(new URL(ROLE_HOME[role], request.url));
    return NextResponse.next();
  }

  if (!role) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (!canAccess(role, pathname)) {
    return NextResponse.redirect(new URL(ROLE_HOME[role], request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Todo excepto assets estaticos de Next y el favicon -- las rutas de API
  // internas (/api/active-calls) tambien pasan por el gate: hace falta
  // sesion valida (de cualquier rol) para leerlas, pero no un rol
  // especifico.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
