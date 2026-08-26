"""Runtime del agente conversacional. Orquesta: intent (AI Router) ->
normalizacion de productos (tools) -> confirmacion -> workflow de
fulfillment (workflow engine -> tools -> domain -> DB).

El agente nunca toca el dominio directamente; todo pasa por
`app.tools.registry.ToolRegistry`.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import ConversationState, OrderLineDraft, get_or_create
from app.ai.base import ParsedItem
from app.ai.router import ai_router
from app.ai.rule_based import CANCEL_WORDS
from app.domain.models import Conversation, WorkflowRun
from app.domain.schemas import AgentMessageIn, AgentTurnOut, CustomerCreate, OrderOut, ToolCallOut
from app.domain.services import CustomerService, OrderService
from app.domain.text_utils import normalize_text
from app.tools.registry import ToolRegistry
from app.workflows.definitions import RESTAURANT_ORDER_FULFILLMENT
from app.workflows.engine import WorkflowEngine
from app.workflows.models import WorkflowRunResult


def _safety_override_intent(message: str, awaiting_confirmation: bool, intent: str) -> str:
    """Red de seguridad determinista, independiente de que proveedor de IA
    este activo: la decision de "el cliente confirmo un pedido real" (->
    stock descontado, dinero comprometido) nunca queda solo en manos de la
    interpretacion de un LLM. Si el proveedor dice "order.confirm" pero el
    mensaje trae una palabra de negacion inequivoca ("no", "cancela"...),
    gana la lectura literal: mejor pedir que confirme de nuevo que crear
    un pedido que el cliente acaba de rechazar. Visto en vivo: un modelo
    barato leyo "No, gracias." como confirmacion.
    """
    if not awaiting_confirmation or intent != "order.confirm":
        return intent
    words = set(normalize_text(message).split())
    if words & CANCEL_WORDS:
        return "order.cancel"
    return intent


class AgentRuntime:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id
        self.tools = ToolRegistry(session, tenant_id)

    async def handle_turn(self, payload: AgentMessageIn) -> AgentTurnOut:
        state = get_or_create(payload.conversation_id, self.tenant_id)
        state.transcript.append(f"cliente: {payload.message}")

        if payload.customer_phone or payload.customer_name:
            await self._resolve_customer(state, payload)

        provider = ai_router.get_provider()
        awaiting_confirmation = state.status == "awaiting_confirmation"
        parsed = await provider.parse_message(payload.message, awaiting_confirmation=awaiting_confirmation)
        parsed.intent = _safety_override_intent(payload.message, awaiting_confirmation, parsed.intent)

        tool_calls: list[ToolCallOut] = []

        if parsed.intent == "handoff":
            await self._call_tool(
                tool_calls, "conversation.transfer_to_human",
                {"conversation_id": state.id, "reason": payload.message},
            )
            state.status = "closed"
            return await self._finish(
                state, "Entiendo, te transfiero con un asesor humano en un momento.", "handoff", [], tool_calls, None
            )

        if parsed.intent == "smalltalk":
            return await self._finish(
                state,
                "Hola, soy el asistente del restaurante. Cuentame que te gustaria pedir.",
                "smalltalk", [], tool_calls, None,
            )

        if parsed.intent in ("order.create", "order.modify"):
            missing = await self._normalize_items(state, parsed.items, tool_calls)
            if parsed.requested_time:
                state.requested_time = parsed.requested_time

            if missing:
                state.status = "collecting"
                response = "No encontre estos productos en el menu, puedes precisarlos: " + "; ".join(missing)
                return await self._finish(state, response, "order.create", missing, tool_calls, None)

            if not state.items:
                return await self._finish(
                    state, "No logre identificar productos en tu pedido, que te gustaria pedir?",
                    "order.create", [], tool_calls, None,
                )

            state.status = "awaiting_confirmation"
            return await self._finish(state, self._build_summary(state), "order.create", [], tool_calls, None)

        if parsed.intent == "order.confirm" and state.status == "awaiting_confirmation":
            order = await self._confirm_order(state, tool_calls)
            if order is None:
                state.status = "collecting"
                reason = state.unresolved[-1] if state.unresolved else "intenta nuevamente."
                response = f"Hubo un problema al confirmar el pedido: {reason}"
                return await self._finish(state, response, "order.confirm", [], tool_calls, None)

            state.status = "closed"
            time_part = f"Te lo entregamos a las {state.requested_time}. " if state.requested_time else ""
            response = (
                f"Listo, tu pedido #{order.id} quedo confirmado por S/ {order.total:.2f}. "
                f"{time_part}Te llegara la confirmacion por mensaje."
            )
            return await self._finish(state, response, "order.confirm", [], tool_calls, order)

        if parsed.intent == "order.cancel":
            state.items.clear()
            state.status = "collecting"
            return await self._finish(
                state, "Sin problema, cancele lo que teniamos armado. Deseas pedir algo mas?",
                "order.cancel", [], tool_calls, None,
            )

        return await self._finish(
            state, "Puedes confirmar si deseas continuar con el pedido? Responde si o no.",
            parsed.intent, [], tool_calls, None,
        )

    async def _resolve_customer(self, state: ConversationState, payload: AgentMessageIn) -> None:
        if state.customer or not (payload.customer_phone or payload.customer_name):
            return
        data = CustomerCreate(name=payload.customer_name or "Cliente telefonico", phone=payload.customer_phone)
        customer = await CustomerService(self.session, self.tenant_id).get_or_create(data)
        await self.session.commit()
        state.customer = {"id": customer.id, "name": customer.name, "phone": customer.phone}

    async def _call_tool(self, tool_calls: list[ToolCallOut], name: str, arguments: dict) -> dict:
        result = await self.tools.call(name, arguments)
        tool_calls.append(ToolCallOut(name=name, arguments=arguments, result=result))
        return result

    async def _normalize_items(
        self, state: ConversationState, parsed_items: list[ParsedItem], tool_calls: list[ToolCallOut]
    ) -> list[str]:
        missing: list[str] = []
        for item in parsed_items:
            result = await self._call_tool(tool_calls, "products.search", {"query": item.query})
            candidates = result.get("products", [])
            if not candidates:
                missing.append(item.raw_text)
                continue
            best = candidates[0]
            state.items.append(
                OrderLineDraft(
                    product_id=best["id"], name=best["name"], quantity=item.quantity,
                    unit_price=best["price"], notes=item.notes,
                )
            )
        return missing

    def _build_summary(self, state: ConversationState) -> str:
        lines = [
            f"{item.quantity} x {item.name}" + (f" ({item.notes})" if item.notes else "")
            for item in state.items
        ]
        total = sum(item.quantity * item.unit_price for item in state.items)
        time_part = f" para las {state.requested_time}" if state.requested_time else ""
        return "Tu pedido seria: " + "; ".join(lines) + f". Total S/ {total:.2f}{time_part}. Confirmas el pedido? (si/no)"

    async def _confirm_order(self, state: ConversationState, tool_calls: list[ToolCallOut]) -> OrderOut | None:
        context: dict = {
            "customer_id": state.customer["id"] if state.customer else None,
            "requested_time": state.requested_time,
            "channel": "whatsapp",
            "items": [
                {"product_id": item.product_id, "quantity": item.quantity, "notes": item.notes}
                for item in state.items
            ],
        }
        engine = WorkflowEngine(self.tools)
        run_result = await engine.run(RESTAURANT_ORDER_FULFILLMENT, context)

        for step in run_result.trace:
            if step.tool:
                tool_calls.append(
                    ToolCallOut(name=step.tool, arguments=step.arguments or {}, result=step.result or {"error": step.detail})
                )

        await self._persist_workflow_run(run_result)

        if run_result.status != "completed":
            state.unresolved.append(run_result.error or "error desconocido")
            return None

        state.items.clear()
        # Releemos el pedido en vez de reusar el dict capturado tras crearlo:
        # los pasos siguientes del workflow (schedule_delivery) lo modifican
        # (status pasa a "scheduled"), y la respuesta al usuario debe reflejar
        # el estado final, no una foto intermedia.
        order_id = run_result.context["order_result"]["order"]["id"]
        return await OrderService(self.session, self.tenant_id).get(order_id)

    async def _persist_workflow_run(self, run_result: WorkflowRunResult) -> None:
        self.session.add(
            WorkflowRun(
                tenant_id=self.tenant_id,
                workflow_key=run_result.workflow_key,
                status=run_result.status,
                context_snapshot=json.dumps(run_result.context, ensure_ascii=False, default=str),
                trace=json.dumps([asdict(step) for step in run_result.trace], ensure_ascii=False, default=str),
            )
        )
        await self.session.commit()

    async def _finish(
        self,
        state: ConversationState,
        response: str,
        intent: str,
        missing: list[str],
        tool_calls: list[ToolCallOut],
        order: OrderOut | None,
    ) -> AgentTurnOut:
        state.transcript.append(f"agente: {response}")
        await self._persist_conversation(state, intent)
        return AgentTurnOut(
            response=response, intent=intent, missing=missing, tool_calls=tool_calls,
            order=order, conversation_id=state.id, status=state.status,
        )

    async def _persist_conversation(self, state: ConversationState, intent: str) -> None:
        convo = await self.session.scalar(
            select(Conversation).where(
                Conversation.tenant_id == self.tenant_id, Conversation.external_id == state.id
            )
        )
        transcript_text = "\n".join(state.transcript)
        customer_id = state.customer["id"] if state.customer else None
        db_status = "closed" if state.status == "closed" else "active"

        if convo:
            convo.transcript = transcript_text
            convo.customer_id = customer_id
            convo.status = db_status
            if state.status == "closed":
                convo.outcome = intent
        else:
            convo = Conversation(
                tenant_id=self.tenant_id,
                external_id=state.id,
                customer_id=customer_id,
                channel="web",
                status=db_status,
                transcript=transcript_text,
                outcome=intent if state.status == "closed" else None,
            )
            self.session.add(convo)
        await self.session.commit()
