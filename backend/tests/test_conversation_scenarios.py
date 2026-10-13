"""Bateria de conversaciones completas, de punta a punta, contra AgentRuntime
real (mismo motor que atiende chat web y telefono). A diferencia de
test_agent_runtime_regressions.py -- que prueba UN bug puntual cada vez --
este archivo corre escenarios REALISTAS completos (saludo -> pedido ->
datos -> confirmacion, o hasta donde termine naturalmente) y solo verifica
que no truene y que el estado final tenga sentido de negocio.

Por que esto y no una infraestructura de "1000 llamadas sinteticas": para
este proyecto, en esta etapa, el valor real esta en cubrir con determinismo
las combinaciones de flujo que ya mordieron en vivo (mensaje con pregunta +
pedido junto, cliente sin telefono, pedido de nuevo en la misma llamada,
etc), no en volumen de fuzzing sin objetivo. Usa el proveedor `rule_based`
(gratis, determinista, sin red) -- exactamente como el resto de la suite."""

import uuid

import pytest

from app.agents.runtime import AgentRuntime
from app.agents.state import get_or_create, reset
from app.domain.schemas import AgentMessageIn
from app.infrastructure.config import settings
from app.infrastructure.db.session import AsyncSessionLocal, init_db
from app.infrastructure.seed import seed_demo_data


@pytest.fixture(autouse=True)
async def demo_db_and_rule_based_provider():
    await init_db()
    await seed_demo_data()
    previous_provider = settings.llm_provider
    settings.llm_provider = "rule_based"
    yield
    settings.llm_provider = previous_provider


def _conversation_id() -> str:
    return f"scenario-{uuid.uuid4()}"


def _phone() -> str:
    return f"+519{str(uuid.uuid4().int)[:8]}"


async def _run_script(conversation_id: str, phone: str | None, script: list[str]) -> list:
    """Corre una lista de mensajes de cliente en orden sobre la MISMA
    conversacion y devuelve la lista de AgentTurnOut, uno por mensaje."""
    turns = []
    async with AsyncSessionLocal() as session:
        runtime = AgentRuntime(session, settings.default_tenant_id)
        for i, message in enumerate(script):
            kwargs = {"message": message, "conversation_id": conversation_id, "channel": "web"}
            if i == 0 and phone:
                kwargs["customer_phone"] = phone
            turns.append(await runtime.handle_turn(AgentMessageIn(**kwargs)))
    return turns


@pytest.mark.asyncio
async def test_scenario_happy_path_delivery_yape():
    conversation_id = _conversation_id()
    try:
        turns = await _run_script(
            conversation_id,
            _phone(),
            [
                "Hola, quiero una hamburguesa clasica y una Inca Kola",
                "Carlos Ramirez",
                "delivery",
                "Av Los Pinos 456, Comas",
                "yape",
                "123",
                "si, confirmo",
            ],
        )
        assert [t.status for t in turns] == [
            "need_name", "need_fulfillment", "need_address", "need_payment",
            "need_yape_code", "awaiting_confirmation", "closed",
        ]
        final = turns[-1]
        assert final.order is not None
        assert final.order.status == "confirmed" or final.order.status == "scheduled"
        assert final.order.payment_method == "yape"
        assert final.order.payment_reference == "123"
        assert final.order.fulfillment_type == "delivery"
        # "Delivery" (cobro del motorizado) se agrega solo en pedidos por
        # delivery -- ver AgentRuntime._confirm_order.
        assert {item.product_name for item in final.order.items} == {
            "Hamburguesa Clasica", "Inca Kola 500ml", "Delivery",
        }
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_scenario_pickup_no_address_needed():
    conversation_id = _conversation_id()
    try:
        turns = await _run_script(
            conversation_id,
            _phone(),
            [
                "Quiero dos Coca-Colas",
                "Maria",
                "recojo en el local",
                "efectivo",
                "confirmo",
            ],
        )
        # Sin "need_address": pickup no la necesita.
        assert "need_address" not in [t.status for t in turns]
        final = turns[-1]
        assert final.status == "closed"
        assert final.order is not None
        assert final.order.fulfillment_type == "pickup"
        assert final.order.delivery_address is None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_scenario_ambiguous_item_then_clarify():
    conversation_id = _conversation_id()
    try:
        turns = await _run_script(
            conversation_id,
            _phone(),
            [
                "Quiero una hamburguesa",  # ambiguo: 4 variantes
                "la doble",
                "Pedro",
                "recojo en el local",
                "efectivo",
                "confirmo",
            ],
        )
        assert turns[0].intent == "order.clarify"
        final = turns[-1]
        assert final.status == "closed"
        assert final.order is not None
        assert final.order.items[0].product_name == "Hamburguesa Doble"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_scenario_menu_question_and_order_in_same_message():
    # Cubre el bug real encontrado hoy: la pregunta de menu ya no debe
    # comerse el pedido que viene en el mismo mensaje.
    conversation_id = _conversation_id()
    try:
        turns = await _run_script(
            conversation_id,
            _phone(),
            [
                "Que bebidas tienen? Deme dos Coca-Colas",
                "Ana",
                "recojo en el local",
                "efectivo",
                "confirmo",
            ],
        )
        final = turns[-1]
        assert final.status == "closed"
        assert final.order is not None
        assert final.order.items[0].quantity == 2
        assert "Coca-Cola" in final.order.items[0].product_name
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_scenario_no_phone_customer_completes_without_crashing():
    # Cubre el KeyError critico encontrado hoy: chat web sin telefono (el
    # caso normal, no uno raro) no debe crashear al confirmar.
    conversation_id = _conversation_id()
    try:
        turns = await _run_script(
            conversation_id,
            None,
            [
                "Quiero un alfajor",
                "Luis",
                "recojo en el local",
                "efectivo",
                "confirmo",
            ],
        )
        final = turns[-1]
        assert final.status == "closed"
        assert final.order is not None
        assert final.order.customer_id is None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_scenario_cancel_then_reorder_in_same_conversation():
    conversation_id = _conversation_id()
    phone = _phone()
    try:
        turns = await _run_script(
            conversation_id,
            phone,
            [
                "Quiero una hamburguesa clasica",
                "Jorge",
                "recojo en el local",
                "efectivo",
                "no, mejor no",  # cancela en la confirmacion
                "Quiero una Inca Kola",
            ],
        )
        cancelled = turns[4]
        assert cancelled.intent == "order.cancel"
        assert cancelled.status == "collecting"

        # El segundo pedido no debe arrastrar fulfillment/pago del anterior.
        second_order_start = turns[5]
        assert second_order_start.status == "need_fulfillment"  # nombre ya en ficha, pero no fulfillment/pago
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_scenario_returning_customer_skips_name_second_call():
    # Mismo telefono, dos conversaciones distintas (dos llamadas separadas):
    # la segunda no debe volver a pedir el nombre.
    phone = _phone()
    first_conversation = _conversation_id()
    second_conversation = _conversation_id()
    try:
        await _run_script(
            first_conversation,
            phone,
            ["Quiero un alfajor", "Sofia Reyes", "recojo en el local", "efectivo", "confirmo"],
        )

        second_turns = await _run_script(
            second_conversation,
            phone,
            ["Quiero una hamburguesa clasica"],
        )
        # No pide el nombre de nuevo -- salta directo a fulfillment.
        assert second_turns[0].status == "need_fulfillment"
    finally:
        reset(first_conversation)
        reset(second_conversation)


@pytest.mark.asyncio
async def test_scenario_requested_time_is_read_back_in_summary():
    conversation_id = _conversation_id()
    try:
        turns = await _run_script(
            conversation_id,
            _phone(),
            [
                "Quiero una hamburguesa clasica para las ocho",
                "Renato",
                "recojo en el local",
                "efectivo",
            ],
        )
        summary = turns[-1]
        assert summary.status == "awaiting_confirmation"
        state = get_or_create(conversation_id, settings.default_tenant_id)
        assert state.requested_time == "20:00"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_scenario_handoff_request_closes_conversation():
    conversation_id = _conversation_id()
    try:
        turns = await _run_script(
            conversation_id,
            _phone(),
            ["Quiero hablar con una persona por favor"],
        )
        assert turns[0].intent == "handoff"
        assert turns[0].status == "closed"
    finally:
        reset(conversation_id)
