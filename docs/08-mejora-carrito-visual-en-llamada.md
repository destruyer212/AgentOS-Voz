# Mejora futura: carrito visual en llamada

## Estado: MVP implementado (oct 2026)

El MVP de este documento ya esta implementado y desplegado -- solo lectura,
sin los botones de confirmar/cancelar desde la web (ver "Decisiones del
MVP real" al final). Pensado como feature aislada y facil de borrar si no
funciona bien:

- `backend/app/domain/order_review.py` -- token firmado (HMAC, sin tabla
  nueva en la base de datos).
- `backend/app/api/v1/order_review.py` -- endpoint publico de solo
  lectura, `GET /order-review/{token}`.
- `backend/app/integrations/wsp_notifications.py` -- `notify_order_review_link`
  (funcion nueva, no toca las existentes).
- Unico punto de enganche con el runtime real: `agents/runtime.py`,
  `_maybe_send_review_link` -- se llama una vez, justo donde el pedido
  llega a "awaiting_confirmation".
- `frontend/app/revisar/[token]/page.tsx` -- pagina publica (sin login,
  `middleware.ts` la deja pasar), se actualiza sola cada 3s mientras la
  llamada sigue activa.

### Decisiones del MVP real (distintas al borrador original de abajo)

- **Solo lectura**: la pagina NO tiene botones de "Confirmar pedido" /
  "Hay un error". Confirmar desde la web ejecutaria el mismo
  `AgentRuntime.handle_turn` que la voz, pero la llamada telefonica
  seguiria esperando indefinidamente sin escuchar nunca la despedida (el
  "colgar solo" depende de que ese turno pase por la llamada real, no por
  este endpoint HTTP aparte) -- un riesgo real de dejar al cliente colgado
  a medio aire. Se dejo fuera a proposito hasta resolver eso bien.
- **Link via WhatsApp, reutilizando el tipo `order_received`** de
  wsp-service (repo separado, otra cuenta AWS) en vez de agregar un tipo
  nuevo -- evita tener que tocar y desplegar ese otro repo. El link va en
  el campo `notes`, el unico de texto libre que ese template deja pasar
  tal cual.
- Un pedido web/WhatsApp (channel != "phone") nunca manda este link --
  ya ve el pedido en su propia pantalla/chat.

## Idea central

Mientras el cliente habla por telefono con AgentOS Voz, el sistema debe poder enviarle un enlace por WhatsApp o SMS para ver su pedido en vivo. El objetivo es reducir errores de voz, darle confianza al cliente y permitir una confirmacion visual antes de cerrar el pedido.

## Flujo propuesto

1. El cliente llama al numero de Telnyx.
2. Deepgram transcribe la voz y el `AgentRuntime` arma el pedido.
3. Cuando ya existe un carrito con productos, el backend genera un link seguro y temporal.
4. El sistema envia el link al cliente por WhatsApp o SMS:
   - "Revisa tu pedido aqui: {link}"
5. El cliente abre una pagina web donde ve:
   - productos
   - cantidades
   - precios
   - delivery o recojo
   - metodo de pago
   - boleta o factura
   - total
6. Antes de confirmar, el agente dice:
   - "Te mande el resumen a WhatsApp. Revisalo y dime si esta correcto."
7. El cliente puede confirmar por voz o tocar un boton en la pagina.

## MVP recomendado

Primera version simple:

- Crear endpoint para generar un link publico temporal del pedido.
- Crear pagina de revision del pedido.
- Enviar link por WhatsApp cuando el pedido llegue a resumen final.
- Mostrar carrito, datos de entrega, metodo de pago y total.
- Agregar botones:
  - Confirmar pedido
  - Hay un error
  - Cancelar

Si el cliente toca "Hay un error", el agente debe retomar por voz:

> "Listo, dime que corregimos."

## Version avanzada

Despues del MVP:

- Actualizacion en tiempo real del carrito mientras el cliente habla.
- WebSocket o Server-Sent Events para sincronizar cambios.
- Estado visual: escuchando, procesando, esperando confirmacion.
- Confirmacion visual y por voz.
- Captura de numero Yape o codigo de aprobacion.
- Captura de codigo de aprobacion de tarjeta.
- Boleta/factura desde la misma pagina.

## Stack tecnico sugerido

- FastAPI para generar y servir sesiones de revision.
- Token firmado temporal para proteger el link.
- React/Vercel para la pantalla visual del pedido.
- WhatsApp service para enviar el link.
- Telnyx + Deepgram para mantener la llamada.
- `AgentRuntime` como cerebro central del pedido.
- Redis opcional para estado en tiempo real si hay mas de un proceso.
- WebSocket o SSE para version live.

## Consideraciones de seguridad

- El link debe expirar en 15 a 30 minutos.
- El token no debe exponer datos internos.
- No debe permitir modificar pedidos ajenos.
- Si hay pago o comprobante, validar confirmaciones sensibles.
- No mostrar datos fiscales completos si no es necesario.

## Beneficio

Esta mejora convierte la llamada en una experiencia hibrida: voz + visual. El cliente no depende solo de lo que entiende la IA por telefono, puede revisar el pedido antes de confirmar y se reducen errores de producto, cantidad, precio, pago y comprobante.
