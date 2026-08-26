# Backend

Backend FastAPI en Python, organizado como monolito modular. Ya es ejecutable
de punta a punta: levanta con SQLite sin configurar nada y resuelve el caso
restaurante completo (pedido en lenguaje natural -> confirmacion -> workflow
de fulfillment -> orden creada con stock descontado).

## Modulos

- `api`: rutas HTTP y dependencias (`v1/products`, `v1/customers`, `v1/orders`, `v1/agent`, `v1/system`, `v1/telephony`).
- `agents`: runtime conversacional (`runtime.py`), memoria de conversacion en curso (`state.py`).
- `ai`: interfaz `LLMProvider` (`base.py`), proveedor `rule_based` (NLU en espanol sin costo, `rule_based.py`) y el router que selecciona proveedor segun `LLM_PROVIDER` (`router.py`).
- `workflows`: motor minimo de pasos tool/condition/end (`engine.py`) y la definicion `restaurant_order_fulfillment` (`definitions.py`).
- `domain`: modelos SQLAlchemy, schemas Pydantic y servicios de negocio (stock, precios, pedidos).
- `tools`: unica puerta de entrada del agente al negocio (`registry.py`).
- `integrations`: notificaciones (simulada, deja rastro en `audit_logs`).
- `infrastructure`: config, sesion async de DB y seed de datos demo.

## Regla

Los agentes solo pueden modificar el negocio invocando tools. Las tools pasan por autorizacion y servicios de dominio:

```text
LLM -> Tool -> Domain Service -> DB transaction
```

## Levantarlo

```bash
cd backend
python -m venv .venv
./.venv/Scripts/pip install -e .
./.venv/Scripts/uvicorn app.main:app --reload
```

Con SQLite por defecto (`DATABASE_URL` en `.env`), sin instalar Postgres. Al
arrancar corre el seed automatico: tenant demo + 7 productos + 1 cliente.
Docs interactivas en `http://127.0.0.1:8000/docs`.

### Proveedor de IA

`LLM_PROVIDER` en `.env` decide quien interpreta los mensajes:

- `rule_based` (por defecto en `.env.example`): NLU por regex, cero costo, sin claves.
- `gemini`: usa `GEMINI_API_KEY` + `GEMINI_MODEL` (ver `app/ai/gemini.py`). Si la
  llamada a Gemini falla por cualquier motivo, el propio proveedor cae
  automaticamente a `rule_based` para ese turno — la conversacion no se rompe.

`backend/.env` (con la clave real) esta en `.gitignore` y nunca se sube al repo;
`.env.example` solo trae el nombre de la variable, vacio.

## Probar el caso restaurante

```bash
# Turno 1: pedido en lenguaje natural
curl -s -X POST http://127.0.0.1:8000/api/v1/agent/turn \
  -H "Content-Type: application/json" \
  -d '{"message":"Hola, quiero dos hamburguesas dobles, una sin cebolla, tres Inca Colas para las ocho","customer_name":"Piero","customer_phone":"+51988776655"}'

# Turno 2: confirmar (usar el conversation_id que devolvio el turno 1)
curl -s -X POST http://127.0.0.1:8000/api/v1/agent/turn \
  -H "Content-Type: application/json" \
  -d '{"message":"si","conversation_id":"<conversation_id>"}'
```

El primer turno normaliza productos por matching difuso (tolera plurales y
"Inca Colas" -> "Inca Kola"), calcula el total y pide confirmacion. El
segundo dispara el workflow `restaurant_order_fulfillment`: crea el pedido
(valida stock, calcula precio, descuenta inventario), programa la entrega y
simula el envio de confirmacion — todo auditado en `audit_logs` y
`workflow_runs`, visibles en `GET /api/v1/system/audit-logs` y
`GET /api/v1/system/workflow-runs`.

Si el stock no alcanza, el workflow falla de forma controlada y el agente
responde explicando el problema en vez de romper la conversacion.

## Telefonia real (Twilio)

`app/api/v1/telephony.py` conecta llamadas telefonicas de verdad al mismo
`AgentRuntime` que usa el chat — no es un motor aparte, es el mismo cerebro
con otro canal de entrada. El `CallSid` de Twilio se usa directamente como
`conversation_id`.

Webhooks (form-urlencoded, los manda Twilio):

- `POST /api/v1/telephony/voice/incoming` — se dispara al recibir la llamada. Saluda y abre un `<Gather>` de voz.
- `POST /api/v1/telephony/voice/turn` — recibe el texto ya transcrito por Twilio (`SpeechResult`), lo procesa como cualquier mensaje del agente y responde con TwiML (`<Say>` + siguiente `<Gather>`, o `<Hangup/>` si el pedido se cerro).
- `POST /api/v1/telephony/voice/status` — callback de fin de llamada: limpia el estado en memoria y deja un `audit_log`.

### Que falta para que suene un telefono de verdad

1. **Credenciales** (`TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` en `.env`) — Account SID + Auth Token alcanzan para todo esto, no hace falta una API Key/Secret aparte.
2. **Un numero de telefono Twilio comprado** — tiene costo (aunque una cuenta Trial trae credito gratis). No se compra automaticamente: hay que decidirlo explicitamente.
3. **Una URL publica** para los webhooks — Twilio no puede llamar a `localhost`. Para desarrollo: un tunel (`ngrok http 8000`, o similar). En produccion: el dominio real del deploy.
4. Configurar en el numero de Twilio (consola o API):
   - Voice webhook -> `https://<tu-url-publica>/api/v1/telephony/voice/incoming` (POST)
   - Status callback -> `https://<tu-url-publica>/api/v1/telephony/voice/status` (POST)

Con eso, cualquiera que marque el numero de Twilio habla con el mismo agente que ya funciona por chat, y el pedido que resulte pasa por el mismo `workflow` y queda en la misma base de datos.

### Nota de seguridad

Twilio firma cada webhook (`X-Twilio-Signature`). La validacion esta
implementada (`verify_twilio_signature`) pero **deshabilitada por defecto**
(`TWILIO_VERIFY_SIGNATURE=false`): activarla mal detras de un tunel que no
reescribe bien los headers de host puede tumbar llamadas reales con un 403
silencioso, que es peor que no validar en desarrollo. Activar
`TWILIO_VERIFY_SIGNATURE=true` una vez desplegado en una URL fija con HTTPS
real.
