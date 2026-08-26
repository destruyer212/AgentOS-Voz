# Contexto Del Proyecto

## Vision

AgentOS Voz sera una plataforma SaaS multiempresa para crear agentes telefonicos y de voz que no solo respondan, sino que ejecuten procesos empresariales completos.

La llamada, el chat web o WhatsApp son canales de entrada. Debajo debe existir un sistema serio:

- runtime de agente
- router de IA
- herramientas autorizadas
- workflow engine
- memoria
- base de conocimiento
- core de negocio
- auditoria
- observabilidad
- integraciones

## Caso inicial

Restaurante.

El agente debe poder atender una conversacion como:

> Hola, quiero dos hamburguesas dobles, una sin cebolla, tres Inca Colas para las ocho.

Y convertirla en proceso:

```text
identificar cliente
detectar intencion
normalizar productos
validar stock
calcular precio
aplicar promociones
pedir confirmacion
crear pedido
reservar/descontar stock
programar entrega
enviar confirmacion
cerrar llamada
```

## Expansion futura

La arquitectura debe poder reutilizarse para:

- restaurantes
- hoteles
- clinicas
- salones de belleza
- talleres
- inmobiliarias
- tiendas
- servicios profesionales

El software no debe quedar amarrado a restaurantes. Restaurante es el primer dominio para validar el motor.

## Diferenciador

El producto fuerte no es que la IA hable. El producto fuerte es que un administrador pueda configurar agentes, herramientas, memoria, reglas y workflows visuales para que la IA ejecute operaciones reales con seguridad.

En terminos simples:

```text
n8n especializado
+ agentes de voz
+ memoria empresarial
+ herramientas seguras
+ core multi-tenant
```
