# Arquitectura

## Arquitectura logica

```text
Canales
  Web | Telefono | WhatsApp | App | Chat
    |
Realtime
  WebRTC | SIP | Audio | VAD | Turn Detection
    |
Agent Runtime
  conversacion | contexto | interrupciones | handoff
    |
AI Router
  Gemini | Ollama | OpenAI | futuros proveedores
    |
Intent + Memory + Knowledge
    |
Tool Engine
  clientes | pedidos | stock | calendario | pagos | notificaciones
    |
Workflow Engine
  trigger | condition | switch | wait | tool | http | webhook | human | end
    |
Business Core
  clientes | productos | pedidos | inventario | sucursales | promociones
    |
Data
  PostgreSQL | Redis | pgvector | audit log
    |
Integrations
  n8n | WhatsApp | ERP | POS | CRM | email | APIs
```

## Backend como monolito modular

No empezamos con microservicios. Empezamos con un backend unico, pero con fronteras claras:

```text
backend/app/
├── api/              endpoints, dependencias y versionado HTTP
├── agents/           runtime, perfiles, prompts, memoria y handoff
├── ai/               router e interfaces de proveedores LLM
├── workflows/        motor, nodos, expresiones y ejecuciones
├── domain/           reglas de negocio deterministas
├── tools/            herramientas que el agente puede invocar
├── integrations/     Twilio, WhatsApp, n8n, POS, ERP, CRM
└── infrastructure/   DB, Redis, eventos, config, observabilidad
```

## Frontend modular

```text
frontend/
├── app/              rutas y pantallas principales
├── components/       UI reutilizable
├── features/         modulos de producto
└── lib/              clientes API, utilidades y tipos compartidos
```

Features esperadas:

- dashboard
- agentes
- workflow builder
- llamadas/conversaciones
- clientes
- productos
- inventario
- pedidos
- integraciones
- analitica

## Regla de oro de seguridad

```text
LLM
  -> Tool
  -> Authorization
  -> Domain Service
  -> Database transaction
```

Prohibido para el LLM:

- ejecutar SQL directo
- cambiar inventario directo
- cambiar precios directo
- emitir reembolsos sin policy
- acceder a datos de otro tenant

## Multi-tenancy

Toda entidad empresarial debe tener `tenant_id`:

- branches
- users
- agents
- customers
- products
- inventory
- orders
- calls
- conversations
- workflows
- integrations
- audit_logs

El diseno debe asumir desde el dia uno que varios negocios viven en la misma plataforma sin mezclar datos.
