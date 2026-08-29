# Estado del motor conversacional y brechas pendientes

**Fecha:** 2026-08-27
**Alcance:** `AgentRuntime` (`backend/app/agents/runtime.py`) y el flujo de recolección de datos de entrega/pago añadido en esta sesión.

**Actualización:** el bug crítico de captura silenciosa en `need_name` y `need_address` fue corregido. El runtime ahora intenta una respuesta literal segura, luego pasa por NLU con contexto de la pregunta pendiente, y si sigue ambiguo repregunta sin guardar texto libre. Hay pruebas de regresión en `backend/tests/test_agent_runtime_regressions.py`.

---

## 1. Resumen ejecutivo

Hoy se llevó el flujo de pedido de "toma el pedido y confirma" a "toma el pedido, resuelve ambigüedad de menú, pregunta datos de entrega y pago". Eso funciona. Pero al reproducir en vivo el reporte de "le dije que agregue algo y no me dejó", encontré la causa raíz exacta: **dos de los cuatro sub-estados de recolección de datos (nombre y dirección) capturan CUALQUIER texto como si fuera la respuesta literal**, sin verificar que realmente lo sea. Si el cliente dice algo que no está en una lista fija de palabras clave de edición, su intención se pierde en silencio y se guarda como si fuera su nombre o su dirección.

No es un problema de latencia ni de Gemini. Es un problema de arquitectura: se está usando coincidencia de palabras clave (heurística) donde hace falta comprensión de lenguaje real (NLU). Abajo está la evidencia, la causa, y el rediseño recomendado.

---

## 2. Qué se construyó hoy (funciona, verificado con pruebas reales)

| Capacidad | Cómo se probó |
|---|---|
| Preguntas de menú con opciones reales por categoría (bebida/hamburguesa/acompañamiento/postre) | `"hay algo para tomar?"` → lista las 5 bebidas reales con precio |
| Desambiguación cuando el pedido es genérico ("una hamburguesa" sin variante) | Detecta empate de score entre productos y pregunta cuál, en vez de agarrar el primero alfabético (bug real que existía antes) |
| Edición de líneas ya pedidas (aumentar/quitar/agregar) vía acción explícita del NLU | `action: add\|remove\|increase\|decrease` en el schema de Gemini + fallback por prefijos en `rule_based.py` |
| Recolección secuencial de nombre → recojo/delivery → dirección (si aplica) → forma de pago | Un dato a la vez, sin repetir lo que el cliente ya dio (cliente recurrente por teléfono no repite nombre/dirección) |
| Evento tardío de transcripción después de colgar ya no revive una conversación fantasma ni intenta hablarle a una llamada muerta | Reproducido en una llamada real: `call.transcription` llegó ~después de `call.hangup`, causaba `speak` 422 en loop. Fijado con un set de "llamadas colgadas" (`telephony_telnyx.py`) |
| Edición durante fulfillment/pago combinada en el mismo mensaje ("delivery y quiero agregar agua") | Antes ignoraba la respuesta y repetía la pregunta; ahora aplica ambas cosas en un turno |

---

## 3. Hallazgo crítico (reproducido en vivo, no es especulación)

### 3.1 Reproducción exacta

```
Cliente: Quiero una hamburguesa clasica
Agente:  Para el pedido, ¿a nombre de quién lo dejo?          [status=need_name]

Cliente: me falta una bebida
Agente:  ¿Lo recoges tú en el local o te lo llevamos por delivery?   [status=need_fulfillment]
```

El agente **avanzó** como si "me falta una bebida" fuera el nombre del cliente. No se agregó la bebida, no hubo error, no hay ninguna señal de que algo se perdió. El pedido final habría salido con el "nombre" `"me falta una bebida"` y sin la segunda bebida.

Mismo patrón en la dirección:

```
Cliente: [...pidió delivery...]
Agente:  ¿Cuál es la dirección de entrega?                     [status=need_address]

Cliente: me falta una bebida
Agente:  ¿Pagas en efectivo, Yape o tarjeta?                   [status=need_payment]
```

`"me falta una bebida"` quedó guardado como dirección de entrega.

### 3.2 Causa raíz

En `_handle_detail_answer` (`runtime.py`), el turno solo se interpreta como "el cliente quiere editar el pedido" si el mensaje contiene una palabra de una lista fija (`_ORDER_EDIT_HINTS`: *aumenta, agrega, quita, elimina, cambia, mejor una...*). Si el cliente lo dice de cualquier otra forma natural — "me falta una bebida", "se me olvidó pedir algo", "ah y una coca" sin las palabras exactas — la heurística no lo detecta, y el código simplemente asume que el texto completo *es* la respuesta a la pregunta pendiente.

Para `need_fulfillment` y `need_payment` esto es seguro por diseño: son coincidencia de palabras clave con un `else` explícito que vuelve a preguntar si no reconoce nada (nunca "inventan" una respuesta). Pero `need_name` y `need_address` son captura de texto libre — cualquier texto no vacío se acepta tal cual. Ahí es donde se pierde la intención del cliente sin ningún aviso.

**Esto ya lo arreglé una vez parcialmente hoy** (cuando el mensaje sí contenía una palabra de la lista, tipo "agrega agua"), pero la lista de palabras clave nunca puede cubrir todas las formas naturales de decir lo mismo. Ese es el límite real de un enfoque basado en keywords: funciona hasta que alguien lo dice distinto.

### 3.3 Por qué importa para "que suene a persona real"

Una persona real nunca pierde en silencio lo que el cliente dice. En el peor caso pregunta "¿eso era tu nombre o querías agregar algo?". El bug actual hace lo contrario: absorbe cualquier frase ambigua como si fuera exactamente lo que se preguntó, sin ninguna verificación. Es la clase de falla que un cliente real percibe como "no me está escuchando" — que es literalmente lo que reportaste.

---

## 4. Rediseño recomendado (nivel dios, no parche)

### 4.1 El principio

Dejar de decidir "¿esto es una edición o es la respuesta?" con una lista de palabras. Esa es una tarea de comprensión de lenguaje, y ya existe un módulo para eso: el NLU (Gemini/rule_based). El runtime no debería tratar de adivinarlo con `if palabra in lista`.

### 4.2 Camino rápido (barato) + camino robusto (NLU), en ese orden

Para no perder la ventaja de latencia que ya existe hoy (los sub-estados `need_*` no llaman a Gemini cuando la respuesta es obviamente literal — "delivery", "efectivo", un nombre corto):

1. **Intento rápido, sin LLM:** para `need_fulfillment`/`need_payment`, seguir intentando el match por palabra clave primero (`_match_fulfillment`/`_match_payment` ya existen y son correctos — 0ms, sin costo). Si matchea, resolver y avanzar. Esto cubre el caso común (~80%+ de las respuestas reales son cortas y directas) sin tocar la API.

2. **Si el intento rápido no resuelve nada** (no matchea ninguna palabra clave, en cualquiera de los 4 sub-estados, incluyendo nombre/dirección): en vez de asumir que es la respuesta literal, **pasarlo por el NLU normal** (`provider.parse_message`) pidiéndole explícitamente que además de items, devuelva un campo `detail_answer` estructurado:

   ```json
   {
     "intent": "...",
     "items": [...],
     "detail_answer": {
       "answers_pending_question": true | false,
       "value": "texto limpio de la respuesta, o null"
     }
   }
   ```

   El prompt debe recibir contexto explícito de *qué* se le preguntó (`"Se le pidió el nombre para el pedido"` / `"Se le pidió si es delivery o recojo"` / etc.), igual que hoy se le dice `awaiting_confirmation`. Con eso, el modelo puede distinguir con confianza real "esto es el nombre" vs. "esto es una edición del pedido" vs. "esto es ninguna de las dos cosas, hay que repreguntar" — algo que ninguna lista de keywords puede hacer con cobertura completa.

3. **Aplicar ambas cosas en el mismo turno cuando corresponda** (igual que ya se hizo para fulfillment+edición combinados): si `items` trae cambios, aplicarlos; si `detail_answer.answers_pending_question` es true, tomar `value` como la respuesta y avanzar; si ninguna de las dos cosas aplica, repreguntar explícitamente en vez de adivinar.

### 4.3 Por qué este orden y no "siempre Gemini"

Ir siempre a Gemini en los 4 sub-estados sería más simple de código, pero mete ~1-1.3s de latencia extra en el caso más común (una respuesta de una palabra: "delivery", "efectivo", "Carlos"), que es exactamente lo que se pidió evitar ("necesito que sea más rápido"). El camino rápido + fallback a NLU solo cuando hace falta es el balance correcto: rápido en el caso común, correcto siempre.

### 4.4 Alcance del cambio

Toca solo `_handle_detail_answer` y el schema/prompt de `ai/gemini.py` (agregar `detail_answer` igual que se agregó `action` hoy). No requiere cambios de modelo de datos ni de frontend. Es un cambio acotado y de alto impacto — recomiendo hacerlo antes de seguir agregando features al flujo de pedido, porque cualquier cosa nueva que se agregue va a heredar el mismo agujero mientras no se corrija la raíz.

---

## 5. Otros hallazgos menores (deuda técnica, no bloqueantes)

- **`"aumenta las papas a dos"` es ambiguo.** El modelo interpreta "quantity" como *cuánto sumar*, no como *el total deseado*. Con papas ya en 1, terminó en 3 (sumó 2) en vez de 2 (fijar a 2). Es una ambigüedad real del lenguaje natural ("a dos" = fijar vs. "en dos" = sumar) que el schema actual no distingue. Baja frecuencia esperada, pero si se hace el rediseño de la sección 4 es un buen momento para agregar un tercer valor de acción (`"set"`) al esquema.
- **`ambiguous` en `products.search`** depende de un empate exacto de score (float redondeado a 4 decimales). Robusto para el catálogo actual; si se agregan productos con nombres muy parecidos entre categorías distintas, vale la pena revisar caso por caso.
- **Watchdog de silencio vs. llamada recién colgada**: ya cubierto por el fix de `_is_hung_up`, pero si el watchdog está a mitad de su `sleep()` justo cuando llega el hangup, se cancela correctamente (`_cancel_watchdog` en el handler de `call.hangup`) — verificado por lectura de código, no por prueba en vivo todavía.

---

## 6. Latencia: qué se hizo y cuál es el techo real

Ya aplicado (sesiones previas): `temperature=0`, `max_output_tokens=400`, sin `thinking_config` (el modelo lo rechaza con 400). Baseline medido: ~1.1-1.3s por llamada a Gemini.

Lo nuevo de hoy que **agrega** latencia condicionalmente: los sub-estados `need_*` NO llaman a Gemini en el caso normal (match por palabra clave, ~0ms) — esto ya es rápido. Solo se paga el costo de Gemini cuando el mensaje contiene una palabra de edición reconocida. El rediseño de la sección 4 mantiene esa misma propiedad (rápido cuando se puede resolver por keyword, NLU solo cuando hace falta).

El resto del techo de latencia (STT de Deepgram + TTS de Telnyx + red) no es código nuestro y ya se investigó a fondo en sesiones anteriores. Para bajar más de ahí hace falta la arquitectura de streaming/VAD que se evaluó y se decidió posponer (la propuesta "V2 Voice Engine"), no un ajuste de prompt.

---

## 7. Plan de acción sugerido (orden de prioridad)

1. **Corregido:** causa raíz de la sección 4 (nombre/dirección capturando texto no relacionado en silencio).
2. **Corregido:** acción `"set"` para cuantificar "aumenta X a N" correctamente.
3. Revisar comportamiento del watchdog en una llamada real después del fix de `_is_hung_up` (confirmar en vivo, no solo por lectura de código).
4. Backlog, no urgente: extender `detail_answer` del punto 4 para también soportar "cambiar de opinión" sobre un dato ya dado (ej. cliente ya dijo delivery pero después dice "mejor recojo, olvida la dirección").
5. **Corregido:** reflejar `fulfillment_type`/`payment_method`/`delivery_address` en el frontend (`OrderSummaryCard`, `OrdersTable`, detalle de `/llamadas`). El tipo `OrderOut` en `frontend/lib/types.ts` y las vistas ya muestran esos datos.

---

## 8. Segunda pasada de hardening (misma fecha, después del punto 7)

Con el rediseño de la sección 4 ya implementado y probado, hice una auditoría adicional buscando específicamente bugs lógicos de conversación real (no solo sintaxis/lint). Encontré y corregí uno serio:

**Bug: pedido duplicado al desambiguar un producto con pausa ("quiero una hamburguesa, BBQ").**
`_SAUCE_WORDS` en `rule_based.py` incluía `"bbq"`, pensado para reconocer salsa barbacoa como nota — pero colisiona con el producto real "Hamburguesa BBQ". Al sacar "bbq" de esa lista (fix directo), apareció un bug más serio como efecto secundario: "hamburguesa" y "BBQ" se parseaban como DOS items separados; el primero quedaba ambiguo (pregunta "¿cuál hamburguesa?") pero el segundo YA se agregaba resuelto como "Hamburguesa BBQ" — si el cliente contestaba "BBQ" a la pregunta, el sistema sumaba una segunda unidad y el pedido terminaba con 2 hamburguesas BBQ cobradas en vez de 1.

Corregido en `AgentRuntime._normalize_items` (`runtime.py`): cuando un término queda ambiguo en un turno, se recuerdan sus tokens; si otro item del MISMO turno resuelve a un producto cuyo nombre contiene esos tokens, se descarta en vez de agregarse — es casi seguro la aclaración de la misma frase, no un pedido nuevo. Reproducido, corregido, y cubierto con una prueba de regresión (`test_ambiguous_item_clarification_does_not_also_add_a_duplicate_item`).

Verificado además, sin encontrar problemas: lint (`ruff check`) limpio, suite completa (9/9) verde, fallback de `AIRouter` ante `LLM_PROVIDER` inválido, y una simulación end-to-end completa (cremas → bebida genérica → nombre → delivery → dirección → pago → confirmación → segundo pedido en la misma llamada sin arrastrar datos del pedido anterior) contra el proveedor `rule_based`.

Backend, túnel de Telnyx y webhook re-verificados y re-desplegados con todo lo anterior aplicado.

---

## 9. Voice Engine V2 -- reescritura a streaming (en curso)

Se decidió ir directo a la arquitectura de streaming completa para bajar la latencia percibida (de ~2.5-4s por turno hacia el rango ~500-800ms que logran sistemas como Vapi/Retell/Bland.ai), en vez de seguir afinando la arquitectura por turnos actual. Plan en 5 fases, cada una validada contra la API real antes de construir la siguiente encima (misma disciplina de todo el proyecto: nunca asumir el shape de una API nueva).

**Fase 1 -- COMPLETADA Y VALIDADA EN UNA LLAMADA REAL.** Nuevo endpoint WebSocket (`app/api/v1/telephony_telnyx_stream.py`) que recibe el audio crudo de Telnyx Media Streaming (`streaming_start`, `stream_track=both_tracks`, `stream_bidirectional_mode=rtp`, `stream_bidirectional_codec=PCMU`), en PARALELO al flujo de Call Control existente -- no lo toca ni lo reemplaza. Apagado por default (`MEDIA_STREAMING_ENABLED=false`); se prendió solo para esta prueba. Validado dos veces:
1. Localmente, con un cliente que simula exactamente los mensajes de Telnyx (`connected`/`start`/`media`/`dtmf`/`stop`) -- confirma que nuestro parser es correcto sin gastar una llamada real.
2. En una llamada real completa (~100s): conectó via el tunel (wss:// sobre cloudflared), recibio ambos tracks (inbound=caller, outbound=agente) a cadencia real de ~20ms, y cerro limpio con el evento `stop` al colgar. Cero errores, cero interferencia con la conversacion (que siguio andando exactamente igual por Call Control).

**Bloqueante original para Fase 2 y 3 (ya superado en la sección 9.1):** hacía falta una cuenta y API key propia de Deepgram (`DEEPGRAM_API_KEY` en `.env`). Hasta ese punto Deepgram solo se usaba indirectamente, a través de la integración administrada por Telnyx (`transcription_start`) -- para conectarnos nosotros mismos en tiempo real (STT) y para Aura-2 (TTS en streaming, con voces en español latinoamericano validadas) hacía falta acceso directo a la API de Deepgram.

Fases previstas en ese momento:
- **Fase 2:** conectar nuestro propio STT en tiempo real de Deepgram sobre el audio de Media Streaming, en modo observacion (comparar contra las transcripciones que ya da Telnyx, todavia sin manejar la conversacion).
- **Fase 3:** VAD sobre el audio crudo para barge-in instantaneo + Aura-2 en streaming para la voz del agente (sentencia por sentencia, no esperar el texto completo).
- **Fase 4:** conectar `AgentRuntime` (el cerebro, sin cambios) a este nuevo pipeline, detras de un flag, con el camino actual (Call Control) intacto como respaldo.
- **Fase 5:** validacion en llamadas reales, ajuste de umbrales, y recien ahi retirar el camino viejo.

### 9.1 Fases 2, 3 y 4 -- COMPLETADAS. Primer pedido real de punta a punta via streaming.

Se salto directo a construir el puente completo (`app/integrations/voice_agent_bridge.py` + `app/api/v1/agent_llm_proxy.py`) en vez de hacerlo observacional primero, dado el nivel de validacion ya logrado en Fase 1. Resultado en la primera llamada real de prueba: **pedido completo confirmado y guardado en la base de datos** (Hamburguesa Vegetariana + Inca Kola, delivery, Yape, S/ 22.40) hablando con Deepgram Voice Agent de punta a punta -- Telnyx nunca corrio su flujo viejo de Call Control en paralelo.

**Bug real encontrado y arreglado EN VIVO, durante la llamada:** el endpoint `/agent-llm-proxy/.../chat/completions` respondia JSON plano; Deepgram pedia `stream: true` y esperaba Server-Sent-Events como cualquier proveedor OpenAI-compatible real. Sin eso, cada turno fallaba con `FAILED_TO_THINK` y el agente volvia a saludar desde cero -- el llamante quedo en un loop de saludos repetidos hasta que se desplego el fix (agregar una respuesta SSE valida en `_chat_completion_stream`). Confirmado con la MISMA llamada telefonica: despues del fix, el pedido avanzo y se cerro sin un solo error mas.

**Segundo hallazgo, mas chico:** el nuevo endpoint no tenia el lock por-conversacion que el flujo viejo de Telnyx si tenia (`get_lock`). Con el que llama hablando en frases cortas, Deepgram a veces manda dos turnos casi simultaneos ("Calle" y "UTP" como dos finales separados), y sin el lock se procesaron sin sincronizar -- la direccion quedo guardada como "Calle" en vez de la direccion completa. Ya corregido (mismo lock que usa `telephony_telnyx.py`), pendiente de reconfirmar en otra llamada.

**Lo que esto valida:** el diseño de "Deepgram maneja voz, `AgentRuntime` maneja negocio" funciona en la practica, no solo en teoria -- mismo catalogo, mismo stock, misma logica de slot-filling de hoy, corriendo detras de un proveedor de voz completamente distinto sin tocar una linea de `runtime.py`.

### 9.2 Bug critico encontrado en vivo: Gemini colgado = silencio muerto en la llamada

Reportado por el usuario: "le hablaba y no respondia, se quedo colgado". Diagnostico exacto en el log: el SDK de Gemini (con sus reintentos internos via `tenacity`) tardo **36 segundos** en darse por vencido y recien ahi caer al fallback `rule_based` -- para cuando eso paso, el que llamaba ya habia colgado frustrado. Mientras tanto, nuestro endpoint `/agent-llm-proxy/.../chat/completions` estaba bloqueado esperando esa respuesta, asi que Deepgram nunca recibio nada que decir: silencio total del lado del agente.

Esto no es un bug nuevo de hoy -- es un riesgo que siempre existio (el flujo viejo de Call Control tiene el mismo `await` sin timeout sobre Gemini), simplemente no se habia manifestado en una llamada real hasta ahora.

**Corregido:** `GeminiProvider.parse_message` ahora envuelve la llamada real en `asyncio.wait_for(..., timeout=4.0)` -- generoso sobre el baseline medido (~1.1-1.3s) pero muy por debajo de los 36s que tardaba el SDK en rendirse solo. Si Gemini no responde en 4s, cae al fallback `rule_based` de inmediato en vez de dejar la llamada en silencio.

**Tambien de paso:** se cambio el modelo de escucha de Deepgram de `nova-3` a `flux-general-multi` (detecta fin de turno en <400ms via modelo semantico, en vez del fallback acustico lento de nova-3). Validado contra la API real antes de desplegarlo. Riesgo real observado: al ser multilenguaje, en un caso confundio una frase en español con ingles ("Hello." transcrito de lo que el usuario realmente dijo) -- no causo el incidente de los 36s (esos son dos problemas distintos y confirmados por separado en el mismo log), pero es una fuente de error a vigilar; si vuelve a pasar, la solucion documentada por Deepgram es fijar `language_hint` a español en vez de dejar la deteccion automatica abierta a los 10 idiomas.

**Pendiente, no urgente:** el flujo nuevo (Voice Agent bridge) no tiene un equivalente al watchdog de silencio del flujo viejo (`_arm_watchdog`/`SILENCE_TIMEOUT_SECONDS` en `telephony_telnyx.py`) -- si algo se cuelga por una causa distinta a esta ya corregida, hoy no hay red de seguridad que reintente o cuelgue con disculpa en el nuevo camino. Vale la pena portarlo cuando haya tiempo.

### 9.3 Pasada de hardening despues del incidente: 4 bugs reales mas

A pedido explicito de revisar todo antes de seguir, se releyo con calma `voice_agent_bridge.py`, `agent_llm_proxy.py` y `runtime.py` completos (no solo lo tocado en el apuro del incidente). Encontrados y corregidos:

1. **Excepciones de tareas nunca retiradas en el puente.** `asyncio.wait(..., return_when=FIRST_COMPLETED)` no relanza solo la excepcion de la tarea que termino -- si Deepgram cerraba la conexion con un error, quedaba como "Task exception was never retrieved" en el log sin mostrar la causa real, y la tarea que seguia viva se cancelaba sin esperarla a que terminara de verdad. Corregido: se retira y loguea la excepcion de la tarea terminada, y se espera (`await`) a la tarea cancelada antes de cerrar la conexion.

2. **Sin red de seguridad generica en el endpoint "think".** El timeout de Gemini (9.2) cubre esa causa puntual, pero CUALQUIER otra excepcion inesperada de `AgentRuntime` seguia devolviendo un 500 crudo a Deepgram -- mismo efecto (`FAILED_TO_THINK`, sesion muerta, Telnyx reconecta desde el saludo). Agregado un `try/except` de ultima instancia que responde con una disculpa hablada en vez de un error HTTP.

3. **Direccion incompleta: causa raiz real, no solo la concurrencia.** El candado por-conversacion (9.1) evitaba que dos turnos simultaneos se pisaran, pero no arreglaba el problema de fondo: decir solo "Calle" (sin el nombre) ya se aceptaba como direccion completa, porque "calle" por si sola es una palabra marcador. Corregido: un marcador sin numero ahora exige al menos una palabra mas ("Calle Lima", no "Calle" a secas); sin eso, pasa por NLU en vez de capturar texto incompleto.

4. **`KeyError: 'id'` al confirmar un pedido sin telefono -- bug critico, afectaba el chat web por defecto.** Cualquier conversacion donde nunca se dio un telefono (el caso normal del chat web, que no pide numero salvo que se abra el campo opcional; tambien una llamada con identificador oculto) deja `state.customer` en `None` hasta que `need_name` lo crea como `{"name": ...}` **sin la clave `"id"`** (no hay fila de `Customer` en la base). Dos lugares accedian con corchetes (`state.customer["id"]`) en vez de `.get("id")`: `_confirm_order` y `_persist_conversation`. Resultado: el pedido se armaba bien durante toda la conversacion y **crasheaba justo al confirmar**, con un 500 crudo. Reproducido en vivo contra el backend real antes y despues del fix. Corregido (`.get("id")` en ambos lugares) y cubierto con una prueba de regresion (`test_order_confirms_without_crashing_when_customer_has_no_phone`).

**Ademas:** al intentar dejar el tipo de retorno de `agent_llm_proxy` mas preciso (`dict | StreamingResponse` en vez de `dict`), FastAPI fallo al ARRANCAR la app entera (`FastAPIError: Invalid args for response field`) -- `StreamingResponse` no es un tipo valido para que FastAPI intente armar un modelo de respuesta automatico. Corregido con `response_model=None` explicito en el decorador (el patron recomendado por el propio mensaje de error). Encontrado y corregido antes de que llegara a afectar una llamada real, verificando el arranque (`python -c "import app.main"`) antes de cada redeploy en vez de asumir que un cambio "cosmetico" es sin riesgo.

Suite completa verde (10/10) y `ruff check` limpio despues de todo lo anterior.

### 9.4 Auditoria con 3 agentes en paralelo (dominio, telefonia, frontend)

A pedido explicito, se lanzaron 3 agentes en paralelo con alcance no superpuesto (cada uno sobre su propia lista de archivos, sin tocar el backend en ejecucion ni el frontend en ejecucion) para una revision mas profunda. Los tres confirmaron bugs reales con reproduccion antes de arreglar:

**Dominio/negocio (`ai/rule_based.py`, `domain/services.py`):**
- Pedido perdido en silencio si el mismo mensaje traia una pregunta de menu y un pedido real ("Que bebidas tienen? Deme dos Coca-Colas" -> se clasificaba entero como `menu.inquiry`, dinero real perdido). Arreglado separando el mensaje por clausulas.
- "12 am" se interpretaba como mediodia en el proveedor `rule_based` (`gemini.py` ya lo tenia bien resuelto -- inconsistencia entre proveedores).
- Lineas duplicadas del mismo producto en un `OrderCreate` no se sumaban antes de validar contra el stock (el `UPDATE` atomico ya evitaba la sobreventa real, pero el mensaje de error era enganoso).
- 4 pruebas de regresion nuevas. Suite final: **14/14**.

**Telefonia (`voice_agent_bridge.py`, `agent_llm_proxy.py`, `telephony_telnyx.py`, `agents/state.py`):**
- **Telefono corrupto en el puente nuevo**: el `+` de un numero E.164 se mandaba sin URL-encode en el query string hacia `agent_llm_proxy.py`; al parsearlo, `+` se decodifica como espacio (`application/x-www-form-urlencoded`). Cada llamada de un cliente recurrente creaba una ficha de cliente duplicada en vez de encontrar la existente. Reproducido con la misma clase `QueryParams` que usa FastAPI. Arreglado con `urllib.parse.quote`.
- **Llamadas fantasma reabiertas, ahora tambien en el puente nuevo**: la proteccion contra eventos tardios post-hangup (`_hung_up_calls`) solo vivia en `telephony_telnyx.py` (flujo viejo). Se movio a `app/agents/state.py` como registro compartido (`mark_hung_up`/`is_hung_up`) y `agent_llm_proxy.py` ahora tambien lo consulta.
- Red de seguridad generica ampliada para cubrir tambien el parseo del body (antes solo envolvia la llamada a `AgentRuntime`).

**Frontend (`ChatPanel.tsx`, `lib/types.ts`):**
- Los sub-estados nuevos (`need_name`/`need_fulfillment`/`need_address`/`need_payment`) se mostraban en crudo en la cabecera del chat de prueba en vez de un texto legible.
- Condicion de carrera al apretar "Nueva conversacion" mientras un turno anterior seguia esperando respuesta -- esa respuesta tardia reinyectaba datos de la sesion vieja en el chat "nuevo".
- Accesibilidad: dos botones solo-icono sin nombre accesible.
- `fulfillment_type` tipado mas estricto en TypeScript de lo que el backend realmente puede enviar (`OrderCreate` publico no valida el valor con un enum).
- `tsc --noEmit` y `npm run build` limpios.

**Encontrado por el orquestador durante la revision final propia (no por los agentes):** al intentar dejar el tipo de retorno de `agent_llm_proxy` mas preciso, FastAPI fallo al ARRANCAR la app entera. Corregido con `response_model=None` explicito, verificando el arranque (`python -c "import app.main"`) antes de cada redeploy desde ese momento en vez de asumir que un cambio "cosmetico" es sin riesgo.

Todo integrado, verificado en conjunto (`pytest` 14/14, `ruff` limpio, `import app.main` limpio) y validado con una llamada real completa de punta a punta antes de este resumen.

### 9.5 Respuesta a la auditoria generica de arquitectura (sin visibilidad del codigo real)

Se recibio una auditoria de arquitectura generada por otro asistente sin acceso al codigo real del proyecto. Varios de sus "problemas" ya no aplican (streaming falso -> el Voice Agent bridge de hoy YA hace streaming real de audio incremental via Deepgram, con TTFA bajo, validado en llamadas reales; barge-in -> ya implementado via `UserStartedSpeaking` -> `clear`, tambien validado en vivo). Tres puntos si eran gaps reales y se atacaron:

**Observabilidad (implementado hoy):** tabla nueva `voice_turn_metrics` + endpoint `GET /api/v1/system/voice-metrics`. Mide lo que SI controlamos (cuanto tarda `AgentRuntime` en pensar cada turno, incluyendo si tuvo que caer de Gemini a `rule_based`), no lo que corre en Deepgram fuera de nuestro proceso (STT/TTS, sin visibilidad nuestra sin instrumentar ese lado tambien). Devuelve p50/p95/promedio y desglose por canal e intencion. Probado en vivo: revela, por ejemplo, que los turnos de `smalltalk` (via Gemini real) promedian ~3s contra <50ms de los pasos de flujo rapido sin LLM -- exactamente el tipo de dato que antes solo se tenia "a sensacion".

**QA automatizado (implementado hoy):** `tests/test_conversation_scenarios.py`, 9 conversaciones completas de punta a punta (no solo el bug puntual que ya se sabia que fallaba) cubriendo: pedido feliz con delivery+Yape, pickup sin direccion, item ambiguo aclarado, pregunta de menu + pedido combinados, cliente sin telefono, cancelar y volver a pedir en la misma llamada, cliente recurrente que no repite datos, hora solicitada, transferencia a humano. No es "1000 llamadas sinteticas" (esa escala no aporta valor real en esta etapa del proyecto) sino una bateria deterministica que cubre las combinaciones que YA mordieron en produccion, corriendo en ~1 segundo como parte de la suite normal.

**Autenticacion multi-tenant real (NO implementado, pendiente de decision):** hoy el tenant se resuelve por un header `X-Tenant-Id` sin validar -- correcto para un solo tenant demo, no para un SaaS real con clientes que no deben ver los datos de otros. Implementar JWT/roles/aislamiento real es una inversion de infraestructura genuina (no es "codigo que falta", es una decision de producto: ¿cuando hay mas de un restaurante usando esto de verdad?). Igual de real: migrar el estado de conversacion en memoria a Redis y SQLite a Postgres -- ambos gaps ciertos para "10,000 llamadas simultaneas", pero prematuros mientras el proyecto sigue en una sola instancia validando el flujo con llamadas reales una por una. No se toco nada de esto sin decision explicita del usuario.

### 9.7 Llamada real revela 3 bugs mas + reversion de `flux-general-multi`

Nueva llamada real (28 ago) con `selena` + `flux-general-multi` ya desplegados. Encontrados en vivo:

1. **Diminutivos no reconocidos.** "hamburguesita"/"papitas"/"bebidita" (muy comunes en espanol hablado) no calzaban contra "Hamburguesa"/"Papas"/"bebida" -- ni en `ProductService.search_scored` ni en `_detect_menu_category`/`_detect_modifier_inquiry`. Arreglado con `_strip_diminutive` en `text_utils.py` (sufijos `-ito/-ita/-itos/-itas/-cito/-cita/-citos/-citas`, con umbral de 6 caracteres para no corromper palabras cortas como "cita"). Bug propio encontrado AL PROBAR el fix: el resultado de sacar el diminutivo pasaba de nuevo por las reglas de plural (`"hamburguesita"` -> `"hamburgues"` -> la regla "termina en -es" lo recortaba de nuevo a `"hamburgu"`) -- corregido devolviendo temprano cuando si hubo diminutivo.

2. **Fragmentos de 1 letra matcheando cualquier producto.** Un pedazo de transcripcion cortado ("C" de "C con papas fritas clasicas", que en realidad era el inicio garbled de "sí, con...") es substring de "Cebolla", "Coca-Cola", "Chicha" -- y el matching parcial le daba 0.6 de score a los 4, disparando una aclaracion sin sentido ("¿Cual C prefieres?"). Arreglado con un minimo de 3 caracteres para que un token cuente en el match parcial (el match EXACTO de palabra completa sigue sin restriccion de largo).

3. **`flux-general-multi` revertido a `nova-3`, por evidencia real, no por preferencia.** En esta misma llamada el modelo multilenguaje detecto frases en español como ingles varias veces ("Hello.", "Tomorrow." como transcripcion de audio real en español), y el usuario reporto el audio "entrecortado" -- consistente con falsos positivos de "el usuario empezo a hablar" (ruido interpretado como voz por el modelo multilenguaje) disparando barge-in de mentira, que corta el audio del agente sin necesidad real. `nova-3` ya se habia validado bien en multiples llamadas reales antes de probar Flux; se prioriza la fiabilidad demostrada sobre la latencia teorica no confirmada en la practica. Si se retoma Flux mas adelante, Deepgram documenta un parametro `language_hint` para sesgar la deteccion -- no probado todavia, requeriria su propia validacion aislada antes de una llamada real.

Los 3 arreglos probados contra el catalogo real antes de desplegar (`search_scored("hamburguesita")` -> 4 variantes; `search_scored("C")` -> 0 resultados) y cubiertos con pruebas de regresion. Suite: 29/29.

### 9.6 Voz: cambio de `aura-2-celeste-es` a `aura-2-selena-es`

Investigadas las 17 voces de Aura-2 en español. Se grabaron 3 muestras reales (mismo saludo, contra la API real) para comparar: la voz en uso (`celeste`, region especificamente colombiana), `selena` (region "Latin American", tono "cercano, calido, natural" -- mejor calce general para un publico peruano) y `antonia` (region argentina, tono entusiasta). Aplicado `selena` como default nuevo tras la comparacion.

### 9.6 Pasada de ingeniería 2026-08-28

Se reescaneó el proyecto completo después de los cambios hechos en otra sesión. Resultado: backend, frontend y docs están coherentes y la batería local queda verde (`pytest` 17/17, `ruff`, `compileall`, `import app.main`, `npm run build`). Hallazgos corregidos en esta pasada: si `VOICE_AGENT_BRIDGE_ENABLED=true` pero falta `PUBLIC_BASE_URL` o `DEEPGRAM_API_KEY`, el webhook de Telnyx ya no salta ciegamente al bridge nuevo; usa Call Control como respaldo y deja el WebSocket en modo observación. También se declaró `websockets` como dependencia directa, se completó `.env.example` con las variables reales del Voice Engine V2, y se alineó "ensalada" con el catálogo real para que el agente no prometa un acompañamiento que luego no puede agregar al pedido.
