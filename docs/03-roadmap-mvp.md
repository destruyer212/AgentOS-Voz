# Roadmap MVP

## Sprint 0 - Fundacion

- repositorio y estructura base
- Docker Compose
- PostgreSQL
- Redis
- FastAPI
- Next.js
- configuracion por entorno
- logging inicial
- documentacion base

## Sprint 1 - Core restaurante

- tenants y sucursales
- clientes
- productos
- variantes
- inventario
- pedidos
- items de pedido
- precios simples
- stock transaccional

## Sprint 2 - Tools

- `get_customer`
- `search_products`
- `check_stock`
- `calculate_price`
- `create_order`
- `reserve_stock`
- `decrement_stock`
- `schedule_delivery`
- `send_confirmation`
- `transfer_to_human`

## Sprint 3 - IA y router

- interfaz `LLMProvider`
- provider Gemini
- provider Ollama
- structured output
- tool calling
- clasificacion de intenciones
- multi-intent basico

## Sprint 4 - Agent runtime

- estado de conversacion
- perfil de agente
- memoria de llamada
- manejo de datos faltantes
- confirmaciones obligatorias
- handoff humano

## Sprint 5 - Workflow engine minimo

- definicion JSON de workflows
- nodos
- edges
- condiciones
- ejecucion paso a paso
- reintentos
- timeouts
- auditoria de ejecucion

## Sprint 6 - Voz web

- LiveKit local/cloud
- WebRTC desde navegador
- microfono
- turn detection
- agente de voz inicial
- transcripcion
- latencia observable

## Sprint 7 - Telefonia real

- SIP/Twilio
- numero telefonico
- llamadas entrantes
- identificacion del llamante
- transferencia
- grabacion opcional
- costos por minuto medibles

## Sprint 8 - Produccion pequena

- RBAC
- aislamiento por tenant
- audit logs
- metricas
- OpenTelemetry
- Grafana
- pruebas de carga
- recuperacion ante fallos
