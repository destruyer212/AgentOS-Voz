# Frontend

Panel de control en Next.js 15 (App Router) + TypeScript + Tailwind CSS.
Habla con el backend real (`../backend`), no hay datos mock: si el backend
no está corriendo, cada página lo dice explícitamente en vez de mostrar
listas vacías engañosas.

## Arquitectura

- **Server Components para lectura** (`app/*/page.tsx`): hacen `fetch` directo
  al backend en el servidor de Next.js. Sin loading spinners para la carga
  inicial, sin exponer la URL del backend al navegador.
- **Server Actions para escritura** (`app/*/actions.ts`, con `"use server"`):
  crear cliente, enviar un turno al agente. Se llaman directo desde
  componentes cliente, sin pasar por una API route intermedia.
- **`lib/api.ts`** es la única pieza que sabe hablar con el backend. Tiene
  `import "server-only"` — si algo lo importa desde un client component, el
  build falla en vez de filtrar la URL del backend al navegador.
- **`lib/types.ts`** espeja a mano los schemas Pydantic del backend
  (`backend/app/domain/schemas.py`). Es un proyecto chico; un generador
  desde OpenAPI seria sobre-ingenieria en este punto.

## Estructura

```text
app/            rutas (dashboard, agente, llamadas, pedidos, productos, clientes, auditoria)
components/     UI generica reutilizable (Sidebar, Badge, CodeBlock, Tabs...)
features/       UI especifica de cada dominio (ChatPanel, OrdersTable...)
lib/            cliente API, tipos y formateo (moneda, fechas, labels)
```

## Paginas

| Ruta | Que muestra |
|---|---|
| `/` | Dashboard: KPIs, pedidos recientes, actividad reciente |
| `/agente` | Chat en vivo contra `/api/v1/agent/turn` para probar el runtime sin llamar por telefono |
| `/llamadas` | Conversaciones y llamadas en vivo, con transcript y detalle del pedido asociado |
| `/pedidos` | Lista de pedidos con items, estado y total (vista admin, ve y puede todo) |
| `/cocina` | Tablero de pedidos por cocinar (rol cocina) |
| `/recepcion` | Tablero de pedidos por confirmar/entregar (rol recepcion) |
| `/productos` | Catalogo con stock, con busqueda difusa (la misma que usa el agente) |
| `/clientes` | Lista + alta manual de clientes |
| `/auditoria` | Audit log completo + trazas de ejecucion del workflow engine |
| `/contabilidad` | Resumen de ingresos: total, tendencia diaria, por entrega y metodo de pago (solo admin) |
| `/contabilidad/productos` | Platos mas pedidos por cantidad e ingreso, y por categoria (solo admin) |
| `/contabilidad/clientes` | Mejores clientes por gasto y por frecuencia (solo admin) |
| `/contabilidad/canales` | Ingresos por llamada telefonica vs chat web vs WhatsApp (solo admin) |
| `/contabilidad/horarios` | Dia de la semana y hora pico de ventas (solo admin) |
| `/contabilidad/comprobantes` | Boletas/facturas SUNAT emitidas, IGV recaudado, y el PDF de cada una (solo admin) |
| `/revisar/[token]` | Carrito visual durante la llamada -- **publica, sin login** (ver docs/08) |

## Login

Todo el panel esta detras de un login (`middleware.ts`) con 3 roles fijos,
sin tabla de usuarios en la base de datos -- ver `lib/auth.ts` y
`lib/auth-shared.ts`:

- **admin**: entra a todo, incluidas `/cocina` y `/recepcion`.
- **cocina**: solo puede entrar a `/cocina`.
- **recepcion**: solo puede entrar a `/recepcion`.

Una sola excepcion a proposito: `/revisar/[token]` (carrito visual durante
la llamada, ver docs/08) es publica -- `middleware.ts` la deja pasar sin
cookie, porque la autorizacion real ahi es el token firmado en la URL.

Usuario/contraseña se configuran por variable de entorno
(`AUTH_ADMIN_USER`/`AUTH_ADMIN_PASS`, `AUTH_COCINA_USER`/`AUTH_COCINA_PASS`,
`AUTH_RECEPCION_USER`/`AUTH_RECEPCION_PASS`, mas `AUTH_SECRET` para firmar
la cookie de sesion) -- ver `.env.local.example`. Sin esas variables, se
usan defaults de desarrollo local (no usar en produccion). `lib/auth.ts`
tiene `import "server-only"`: si algo lo importa desde un client component
por error, el build falla en vez de terminar filtrando las contraseñas al
navegador.

## Levantarlo

Con el backend corriendo (`../backend`, ver su README):

```bash
cd frontend
cp .env.local.example .env.local   # ajusta API_URL si el backend no esta en :8000
npm install
npm run dev
```

Abre `http://localhost:3000`. El backend ya trae CORS habilitado para
`localhost:3000`, aunque en la practica casi todo el trafico va por server
components/actions (mismo servidor, sin CORS de por medio).
