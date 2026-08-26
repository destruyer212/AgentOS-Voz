# Decisiones Tecnicas

## 1. Modular monolith primero

Empezar con microservicios seria prematuro. El MVP necesita velocidad, trazabilidad y limites internos claros.

Decision:

```text
FastAPI modular monolith
```

Salida futura:

```text
Agent Service
Workflow Service
Business Core Service
Integrations Service
```

solo cuando el volumen lo justifique.

## 2. IA intercambiable

Gemini puede ser util para prototipos y voz realtime. Ollama permite pruebas locales y control de costos.

Decision:

```python
class LLMProvider:
    async def generate(...): ...
    async def stream(...): ...
    async def call_tools(...): ...
```

Providers iniciales:

- Gemini
- Ollama
- OpenAI futuro

## 3. Primero voz web, luego telefono

La telefonia real cuesta. El laboratorio inicial debe validar casi todo desde navegador.

Orden:

```text
chat texto
  -> voz navegador
  -> SIP/telefono real
```

## 4. Workflow propio minimo, n8n como apoyo

No conviene construir un n8n completo desde cero al inicio.

Decision:

- workflow engine minimo para procesos internos criticos
- n8n/webhooks para integraciones externas tempranas
- builder visual propio cuando el core ya funcione

## 5. Reglas criticas en codigo

La IA puede interpretar, pero no decidir la verdad contable ni operacional.

Reglas en dominio:

- stock
- precios
- impuestos
- promociones
- descuentos maximos
- autorizaciones
- transacciones

## 6. Auditoria desde el inicio

Cada llamada y cada tool call debe poder reconstruirse.

Eventos minimos:

- call started
- message received
- intent detected
- tool requested
- tool succeeded/failed
- workflow advanced
- order created
- stock changed
- call ended
