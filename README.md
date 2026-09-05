# AgentOS Voz

Plataforma para crear agentes de IA que no solo conversan, sino que ejecutan
procesos de negocio reales: piden un pedido, validan stock, cobran el precio
correcto, confirman, reservan inventario y notifican -- por chat, por
telefono, o por voz de navegador.

El primer caso de uso (para validar el motor completo) es un restaurante:

```text
Cliente llama o escribe
  -> el agente conversa y entiende la intencion
  -> normaliza productos contra el catalogo real
  -> valida stock y calcula el precio
  -> pide confirmacion
  -> crea el pedido (transaccion real, stock descontado)
  -> programa la entrega
  -> notifica la confirmacion
```

No es un chatbot que "suena inteligente". Es un runtime de agente + reglas de
negocio deterministas + un motor de workflows, con el LLM limitado a
interpretar y elegir herramientas -- nunca a decidir la verdad contable u
operacional.

## Estado actual

Esto no es un demo local: **esta en produccion real**, en la nube, atendiendo
pedidos de verdad de un restaurante real (El Olivar Grill, Puente Piedra,
Lima). Ver [CLAUDE.md](CLAUDE.md) para el detalle completo de donde vive
cada pieza (servidor, dominio, base de datos) -- este README solo cubre como
levantarlo en local para desarrollar.

| Pieza | Estado |
| --- | --- |
| Core de negocio (clientes, productos, stock, pedidos, multi-tenant) | Funcionando en produccion |
| NLU en espanol (reglas propias + Gemini real, con fallback automatico) | Funcionando en produccion |
| Motor de tools (unica puerta de entrada del agente al negocio) | Funcionando |
| Motor de workflows (pasos, condiciones, auditoria de ejecucion) | Funcionando |
| Frontend (dashboard, chat con el agente, llamadas, pedidos, productos, clientes, auditoria) | Funcionando (despliegue en la nube sin confirmar, ver CLAUDE.md) |
| Telefonia real -- Telnyx Media Streaming + Deepgram Voice Agent | **En produccion**, atendiendo llamadas reales todos los dias |
| Telefonia -- Twilio | Codigo de respaldo en el repo, no es el camino real de produccion |
| WhatsApp (wsp-service, proyecto/repo aparte) | **En produccion**: avisa pedidos y responde mensajes entrantes con el mismo agente |
| Zonas de delivery (solo Lima, solo cerca de Puente Piedra) + cobro de motorizado | Funcionando en produccion |
| Flujo de cumplimiento cocina -> motorizado -> entregado, con aviso automatico | Funcionando en produccion |
| Voz por navegador (WebRTC) | No empezado |
| Auth / RBAC | No empezado |

El caso de uso completo -- "Hola, quiero dos hamburguesas dobles, una sin
cebolla, tres Inca Colas para las ocho" hasta pedido confirmado con stock
descontado -- funciona hoy por **chat web, API, WhatsApp, y llamada
telefonica real**, contra la base de datos real de produccion.

## Probarlo en unos minutos

```bash
# Backend
cd backend
python -m venv .venv
./.venv/Scripts/pip install -e .
cp .env.example .env          # opcional: agregar GEMINI_API_KEY para NLU real
./.venv/Scripts/uvicorn app.main:app --reload

# Frontend (en otra terminal)
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Abre `http://localhost:3000` y habla con el agente en la pestaña **Agente**.
Sin `GEMINI_API_KEY` el sistema sigue funcionando con un NLU basado en reglas
(cero costo, cero configuracion). Detalle completo en
[backend/README.md](backend/README.md) y [frontend/README.md](frontend/README.md).

## Arquitectura

```text
Canales
  Chat web | API | Llamada telefonica (Twilio / Telnyx / Deepgram bridge) | Voz navegador (pendiente)
    |
Agent Runtime
  estado de conversacion, memoria de turno, handoff a humano
    |
AI Router
  interfaz intercambiable: Gemini (real) | reglas propias (sin costo)
    |
Tool Registry
  unica puerta de entrada al negocio -- el LLM nunca toca la DB directo
    |
Workflow Engine
  pasos, condiciones, reintentos, traza de ejecucion auditable
    |
Domain Core
  clientes, productos, inventario, pedidos -- reglas deterministas en codigo
    |
Data
  PostgreSQL (SQLite solo como default de desarrollo local) | audit log completo
```

Regla de oro, en cualquier canal:

```text
LLM -> Tool -> Domain Service -> DB transaction
```

## Estructura

```text
AgentOS Voz/
├── backend/            FastAPI: runtime del agente, dominio, tools, workflows, telefonia
│   └── app/
│       ├── api/            endpoints HTTP y webhooks
│       ├── agents/          runtime conversacional y memoria de conversacion
│       ├── ai/              proveedores de IA (Gemini, reglas) intercambiables
│       ├── workflows/       motor de pasos/condiciones y definiciones
│       ├── domain/          modelos, schemas y reglas de negocio
│       ├── tools/           unica puerta de entrada del agente al negocio
│       ├── integrations/    Twilio, Telnyx, notificaciones
│       └── infrastructure/  config, base de datos, seed de demo
├── frontend/           Next.js: dashboard, chat, llamadas, pedidos, productos, clientes, auditoria
├── docs/               vision, arquitectura y decisiones tecnicas del proyecto
└── infra/
```

## Stack

| Capa | Tecnologia |
| --- | --- |
| Backend | Python + FastAPI + SQLAlchemy async, desplegado en una instancia EC2 de AWS (systemd) |
| Base de datos | **PostgreSQL real en produccion** (en el mismo EC2), migraciones con Alembic. SQLite solo como default para levantar el proyecto en local sin instalar Postgres |
| IA | Gemini (real) con fallback a NLU por reglas propias |
| Frontend | Next.js 15 + TypeScript + Tailwind (Server Components + Server Actions) |
| Telefonia | **Telnyx Media Streaming + Deepgram Voice Agent** (camino real de produccion). Twilio y Telnyx Call Control quedan como codigo de respaldo, no es lo que atiende llamadas reales hoy |
| WhatsApp | wsp-service -- Node/Baileys, repo y despliegue AWS **separados** de este proyecto, integrado por HTTP contra este backend |

Detalle completo de que esta desplegado, donde, y con que base de datos:
[CLAUDE.md](CLAUDE.md).

## Lo que falta

- Voz por navegador (WebRTC) -- para probar el agente hablando desde el navegador antes de ir a telefonia real.
- Auth / RBAC -- hoy no hay login; cualquiera que le pegue a la API opera como el tenant demo.
- Backups automaticos de la base de datos de produccion -- hoy Postgres corre en el mismo EC2 sin backup automatico, no es un servicio administrado (RDS).
- Confirmar/formalizar el despliegue del frontend en la nube (hoy corre en produccion contra la API real, pero sin un hosting en la nube confirmado -- ver CLAUDE.md).
- Generalizar el dominio mas alla de restaurante (hoteles, clinicas, talleres...) -- el motor ya es generico, el modelo de datos y los prompts todavia estan pensados en restaurante.

Ver [docs/](docs/) para la vision completa y el roadmap por sprints.
