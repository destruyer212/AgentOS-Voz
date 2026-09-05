# AgentOS Voz — estado real (leer esto antes de asumir nada)

Este archivo existe porque varias veces una IA (incluido Claude en otra
sesion) asumio, por los README, que este proyecto "no esta en la nube" o
que la base de datos es SQLite. **Eso es falso.** Los README describen como
se levanta el proyecto en local para desarrollar; este archivo describe
donde vive DE VERDAD hoy, en produccion, atendiendo pedidos reales del
restaurante El Olivar Grill (Puente Piedra, Lima, Peru).

## Si o si, esto YA esta desplegado en la nube

- **Backend:** corre en una instancia **EC2 de AWS** (`us-east-1`), no en
  ninguna PC. Instance ID `i-0a99642bc018609b0`, IP `23.22.118.94`.
- **Dominio real:** `https://api.athenaai.net.pe/api/v1` — es la URL a la
  que llaman Telnyx (llamadas telefonicas reales), wsp-service (WhatsApp) y
  cualquier frontend/cliente HTTP.
- Corre como servicio systemd (`agentos-voz.service`) en
  `/home/ubuntu/AgentOS-Voz/backend`, con su propio `.env` en el servidor
  (nunca en el repo). Sigue arriba solo, sobrevive reinicios del servidor.
- **No hay CI/CD.** El deploy es manual: tar del `backend/` (sin `.env`, sin
  `.venv`, sin cachés) → `scp` al EC2 → extraer sobre el directorio ya
  desplegado → `sudo systemctl restart agentos-voz`. Antes de restart,
  chequear que no haya una llamada en curso (`ss -tnp | grep :8000`).
- **Acceso SSH:** no hay `.pem` disponible. Se entra via **AWS EC2 Instance
  Connect** (`aws ec2-instance-connect send-ssh-public-key`, clave temporal
  ed25519 valida ~60s) con perfil AWS `default`. El grupo de seguridad
  (`sg-0d68e40b402f0fbd7`) solo permite SSH desde la IP actual del que se
  conecta — la IP del usuario cambia seguido, hay que refrescar la regla de
  ingreso (`revoke` + `authorize` puerto 22) antes de cada sesion.

## La base de datos es PostgreSQL real, no SQLite

- Motor: **PostgreSQL**, instalado en el **mismo EC2** que el backend
  (`localhost:5432`, base `agentos_voz`, usuario `agentos_app`) — no es un
  servicio administrado (RDS), asi que no tiene backups automaticos por
  defecto.
- SQLite **solo** aparece como default de `DATABASE_URL` en
  `backend/.env.example`, para que alguien pueda levantar el proyecto en su
  laptop sin instalar Postgres. Eso es exclusivamente para desarrollo local
  — la produccion real nunca usa SQLite.
- Hay migraciones Alembic reales y en uso (`backend/alembic/versions/`, ya
  van 3), no "SQLite crea las tablas solo" como todavia dice algun README
  viejo.

## Telefonia real: Telnyx + Deepgram, no Twilio

- El codigo de Twilio (`app/api/v1/telephony.py`) existe en el repo pero es
  el camino **viejo/de respaldo**, no el que atiende llamadas reales hoy.
- El camino real en produccion es **Telnyx Media Streaming + Deepgram Voice
  Agent** (`app/integrations/voice_agent_bridge.py`,
  `app/api/v1/telephony_telnyx*.py`): Deepgram hace STT/TTS y delega TODO el
  razonamiento a nuestro propio proxy (`agent_llm_proxy.py`), que llama al
  mismo `AgentRuntime` que usa el chat web y WhatsApp.
- Modelos en produccion: STT `nova-3`, TTS `aura-2-celeste-es`, español
  explicito (`language: "es"`).

## WhatsApp: proyecto aparte, ya conectado

- Repo y despliegue **separados**: `C:\whatsapp-service` en esta maquina,
  cuenta de AWS **distinta** a la de AgentOS Voz (perfil `wsp`), su propio
  EC2 (`i-0808347c75beab279`, IP `34.231.190.69`). Node 20 + Baileys.
- Se conecta a AgentOS Voz por HTTP normal contra
  `https://api.athenaai.net.pe/api/v1`: manda avisos de pedido (confirmado /
  ya salio con el motorizado / listo para recoger) y, desde hace poco,
  tambien reenvia los mensajes de WhatsApp entrantes al mismo
  `AgentRuntime` (`/api/v1/agent/turn`, `channel: "whatsapp"`) para que el
  cliente pueda pedir por WhatsApp igual que por llamada.

## Frontend: esto SI hay que confirmarlo, no asumir

A la fecha de este archivo, en el EC2 del backend **no** hay nada de
Next.js corriendo (sin `node_modules`, sin build `.next`) — el frontend NO
esta desplegado ahi. No hay Vercel ni otro hosting confirmado en el repo.
Probablemente el usuario lo corre local (`npm run dev` en `frontend/`,
apuntando a `api.athenaai.net.pe`). **No asumas que esta en la nube: pregunta
o verifica antes de dar por hecho donde vive.**

## Resumen de una linea para no volver a confundirse

Backend + base de datos: **en la nube, en AWS, en produccion, atendiendo
pedidos reales** (Postgres real, no SQLite). Frontend: estado de despliegue
sin confirmar, probablemente local. WhatsApp: proyecto aparte, ya integrado
por HTTP.
