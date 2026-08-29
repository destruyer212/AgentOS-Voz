import uuid

import pytest
from sqlalchemy import select

from app.agents.runtime import AgentRuntime
from app.agents.state import get_or_create, reset
from app.ai.router import ai_router
from app.ai.rule_based import RuleBasedProvider
from app.domain.models import InventoryItem, Product
from app.domain.schemas import AgentMessageIn, OrderCreate, OrderItemIn
from app.domain.services import DomainError, OrderService
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
    return f"test-{uuid.uuid4()}"


def _phone() -> str:
    return f"+519{str(uuid.uuid4().int)[:8]}"


@pytest.mark.asyncio
async def test_pending_name_does_not_swallow_order_edit_as_customer_name():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero una hamburguesa clasica",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                    channel="web",
                )
            )
            assert first.status == "need_name"

            second = await runtime.handle_turn(
                AgentMessageIn(
                    message="me falta una Inca Kola",
                    conversation_id=conversation_id,
                    channel="web",
                )
            )

            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_name"
            assert state.customer
            assert state.customer["name"] == "Cliente telefonico"
            assert any(item.name == "Inca Kola 500ml" for item in state.items)
            assert "a nombre" in second.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_pending_name_does_not_swallow_generic_missing_beverage_phrase():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero una hamburguesa clasica",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                    channel="web",
                )
            )
            assert first.status == "need_name"

            second = await runtime.handle_turn(
                AgentMessageIn(
                    message="me falta una bebida",
                    conversation_id=conversation_id,
                    channel="web",
                )
            )

            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "collecting"
            assert state.customer
            assert state.customer["name"] == "Cliente telefonico"
            assert "bebida prefieres" in second.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_pending_address_does_not_swallow_order_edit_as_delivery_address():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero una hamburguesa clasica",
                    conversation_id=conversation_id,
                    customer_name="Carlos",
                    customer_phone=_phone(),
                    channel="web",
                )
            )
            assert first.status == "need_fulfillment"

            second = await runtime.handle_turn(
                AgentMessageIn(message="delivery", conversation_id=conversation_id, channel="web")
            )
            assert second.status == "need_address"

            third = await runtime.handle_turn(
                AgentMessageIn(
                    message="me falta una Inca Kola",
                    conversation_id=conversation_id,
                    channel="web",
                )
            )

            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_address"
            assert state.delivery_address is None
            assert any(item.name == "Inca Kola 500ml" for item in state.items)
            assert "dirección" in third.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_rule_based_parser_supports_set_quantity_action():
    provider = RuleBasedProvider()

    parsed = await provider.parse_message(
        "aumenta las papas a dos",
        awaiting_confirmation=False,
    )

    assert parsed.intent == "order.create"
    assert len(parsed.items) == 1
    assert parsed.items[0].action == "set"
    assert parsed.items[0].quantity == 2
    assert parsed.items[0].query == "papas"


@pytest.mark.asyncio
async def test_rule_based_parser_keeps_creams_as_item_notes_not_products():
    provider = RuleBasedProvider()

    parsed = await provider.parse_message(
        "Quiero una hamburguesa doble con aji y mayonesa",
        awaiting_confirmation=False,
    )

    assert parsed.intent == "order.create"
    assert len(parsed.items) == 1
    assert parsed.items[0].query == "hamburguesa doble"
    assert parsed.items[0].notes
    assert "aji" in parsed.items[0].notes.lower()
    assert "mayonesa" in parsed.items[0].notes.lower()


@pytest.mark.asyncio
async def test_rule_based_parser_treats_pure_greetings_as_smalltalk():
    # Bug visto en llamada real: "Hola" entraba como item de pedido y el
    # agente contestaba "No encontre Hola en el menu". Un saludo solo no es
    # una busqueda de catalogo.
    provider = RuleBasedProvider()

    for message in ("Hola", "Buenas tardes, hola como estas", "Que tal"):
        parsed = await provider.parse_message(message, awaiting_confirmation=False)
        assert parsed.intent == "smalltalk"
        assert parsed.items == []


@pytest.mark.asyncio
async def test_phone_greeting_does_not_search_menu_or_create_missing_item():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Hola",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                    channel="phone",
                )
            )

        assert turn.intent == "smalltalk"
        assert turn.tool_calls == []
        assert "no encontr" not in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_menu_prices_are_spoken_in_soles_for_voice_tts():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Que bebidas tienen?",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                    channel="phone",
                )
            )

        response = turn.response.lower()
        assert turn.intent == "menu.inquiry"
        assert "s/" not in response
        assert "soles" in response
        assert "soles con 50" in response
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_rule_based_parser_keeps_order_when_message_also_asks_menu_question():
    # Bug real: "Que bebidas tienen? Deme dos Coca-Colas" se clasificaba
    # entero como menu.inquiry (la pregunta de menu dominaba el mensaje
    # completo) y el pedido -- con dinero real de por medio -- se perdia
    # en silencio. El agente solo contestaba el menu y nunca registraba
    # las Coca-Colas.
    provider = RuleBasedProvider()

    parsed = await provider.parse_message(
        "Que bebidas tienen? Deme dos Coca-Colas",
        awaiting_confirmation=False,
    )

    assert parsed.intent == "order.create"
    assert len(parsed.items) == 1
    assert parsed.items[0].quantity == 2
    assert "coca" in parsed.items[0].query.lower()


@pytest.mark.asyncio
async def test_rule_based_parser_stays_menu_inquiry_without_a_real_order_clause():
    # Contraprueba del fix anterior: una pregunta de menu seguida de una
    # frase que NO trae ninguna senal de pedido (sin cantidad, sin verbo de
    # accion conocido) no debe inventar un item de producto con la frase
    # sobrante como query.
    provider = RuleBasedProvider()

    parsed = await provider.parse_message(
        "Que bebidas tienen? Definitivamente quiero probar algo",
        awaiting_confirmation=False,
    )

    assert parsed.intent == "menu.inquiry"
    assert parsed.items == []


@pytest.mark.asyncio
async def test_rule_based_parser_splits_adjacent_known_products_without_comma():
    # En voz el STT no siempre pone coma ni "y". Si el cliente dice
    # "hamburguesa chicha morada", deben ser dos items, no una busqueda rara
    # que termina encontrando solo la chicha y perdiendo la hamburguesa.
    provider = RuleBasedProvider()

    parsed = await provider.parse_message(
        "quiero hamburguesa chicha morada",
        awaiting_confirmation=False,
    )

    assert parsed.intent == "order.create"
    assert [item.query for item in parsed.items] == ["hamburguesa", "chicha morada"]


@pytest.mark.asyncio
async def test_rule_based_parser_midnight_twelve_am_is_not_noon():
    # Bug real: "a las 12 am" (medianoche) se interpretaba igual que
    # "a las 12 pm" (mediodia) porque solo se ajustaba el caso pm. El fix
    # espejo ya existia en gemini._normalize_time; faltaba en el parser de
    # reglas.
    provider = RuleBasedProvider()

    parsed = await provider.parse_message(
        "Quiero una hamburguesa clasica para las 12 am",
        awaiting_confirmation=False,
    )

    assert parsed.requested_time == "00:00"


@pytest.mark.asyncio
async def test_create_confirmed_order_rejects_duplicate_product_lines_over_stock():
    # Bug real: la validacion de stock chequeaba cada linea del pedido por
    # separado contra el mismo `inventory.quantity` sin descontar lo que
    # otra linea del MISMO pedido ya iba a consumir. Con stock=1 y dos
    # lineas de 1 unidad del mismo producto, ambas pasaban el chequeo
    # inicial (1 >= 1) aunque juntas pidieran el doble del disponible. El
    # UPDATE atomico terminaba bloqueando la segunda linea igual, pero con
    # un mensaje enganoso ("se agoto justo antes de confirmar", como si
    # fuera una carrera con OTRO pedido) en vez de avisar de una que no
    # alcanza el stock.
    async with AsyncSessionLocal() as session:
        product = (
            await session.execute(
                select(Product).where(
                    Product.tenant_id == settings.default_tenant_id, Product.sku == "POS-ALF"
                )
            )
        ).scalar_one()
        inventory = (
            await session.execute(
                select(InventoryItem).where(
                    InventoryItem.tenant_id == settings.default_tenant_id,
                    InventoryItem.product_id == product.id,
                )
            )
        ).scalar_one()
        original_quantity = inventory.quantity
        original_reserved = inventory.reserved
        inventory.quantity = inventory.reserved + 1  # deja disponible = 1
        await session.commit()

    try:
        async with AsyncSessionLocal() as session:
            service = OrderService(session, settings.default_tenant_id)
            data = OrderCreate(
                items=[
                    OrderItemIn(product_id=product.id, quantity=1),
                    OrderItemIn(product_id=product.id, quantity=1),
                ]
            )
            with pytest.raises(DomainError, match="Stock insuficiente"):
                await service.create_confirmed_order(data)

        async with AsyncSessionLocal() as session:
            inventory = (
                await session.execute(
                    select(InventoryItem).where(
                        InventoryItem.tenant_id == settings.default_tenant_id,
                        InventoryItem.product_id == product.id,
                    )
                )
            ).scalar_one()
            # el rechazo debe ser todo-o-nada: nada de stock consumido
            assert inventory.quantity == original_reserved + 1
            assert inventory.reserved == original_reserved
    finally:
        async with AsyncSessionLocal() as session:
            inventory = (
                await session.execute(
                    select(InventoryItem).where(
                        InventoryItem.tenant_id == settings.default_tenant_id,
                        InventoryItem.product_id == product.id,
                    )
                )
            ).scalar_one()
            inventory.quantity = original_quantity
            inventory.reserved = original_reserved
            await session.commit()


def test_ai_router_falls_back_to_rule_based_when_provider_is_invalid():
    previous_provider = settings.llm_provider
    settings.llm_provider = "proveedor_inexistente"
    try:
        assert ai_router.get_provider().name == "rule_based"
    finally:
        settings.llm_provider = previous_provider


@pytest.mark.asyncio
async def test_cancel_clears_order_details_before_next_order():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            assert (
                await runtime.handle_turn(
                    AgentMessageIn(
                        message="Quiero una hamburguesa doble para las ocho",
                        conversation_id=conversation_id,
                        customer_name="Carlos",
                        customer_phone=_phone(),
                    )
                )
            ).status == "need_fulfillment"
            assert (
                await runtime.handle_turn(
                    AgentMessageIn(message="delivery", conversation_id=conversation_id)
                )
            ).status == "need_address"
            assert (
                await runtime.handle_turn(
                    AgentMessageIn(message="Av Siempre Viva 123", conversation_id=conversation_id)
                )
            ).status == "need_payment"
            assert (
                await runtime.handle_turn(
                    AgentMessageIn(message="yape", conversation_id=conversation_id)
                )
            ).status == "awaiting_confirmation"

            cancelled = await runtime.handle_turn(
                AgentMessageIn(message="no gracias", conversation_id=conversation_id)
            )
            assert cancelled.status == "collecting"

            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.items == []
            assert state.requested_time is None
            assert state.fulfillment_type is None
            assert state.delivery_address is None
            assert state.payment_method is None

            next_order = await runtime.handle_turn(
                AgentMessageIn(message="Quiero una Inca Kola", conversation_id=conversation_id)
            )
            assert next_order.status == "need_fulfillment"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_ambiguous_item_clarification_does_not_also_add_a_duplicate_item():
    # "hamburguesa" solo es ambiguo (4 variantes); "BBQ" en el mismo mensaje
    # resuelve a "Hamburguesa BBQ". Sin la deduplicacion por tokens, esto
    # dejaba a la vez una pregunta de aclaracion Y un item ya agregado --
    # si el cliente contestaba "BBQ" a la pregunta, terminaba pagando dos
    # hamburguesas BBQ en vez de una.
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero una hamburguesa, BBQ",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                )
            )
            assert first.intent == "order.clarify"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.items == []

            second = await runtime.handle_turn(
                AgentMessageIn(message="BBQ", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert [item.name for item in state.items] == ["Hamburguesa BBQ"]
            assert state.items[0].quantity == 1
            assert second.status == "need_name"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_modifier_inquiry_answers_creams_without_dumping_full_menu():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            turn = await runtime.handle_turn(
                AgentMessageIn(message="Que cremas tienen?", conversation_id=conversation_id)
            )

            response = turn.response.lower()
            assert turn.intent == "menu.inquiry"
            assert "mayonesa" in response
            assert "ketchup" in response
            assert "hamburguesa" not in response
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_ensalada_is_a_real_orderable_accompaniment():
    # El agente no debe prometer "ensalada" como acompanamiento si luego el
    # catalogo no puede resolverla como producto. Esto cubre la coherencia
    # entre conversacion natural y stock/precio real.
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero una ensalada",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                )
            )

            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert turn.status == "need_name"
            assert [item.name for item in state.items] == ["Ensalada Fresca"]
            assert state.items[0].quantity == 1
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_order_confirms_without_crashing_when_customer_has_no_phone():
    # Reproducido en vivo: chat web sin dar telefono (el caso normal --
    # customer_phone es opcional y por defecto no se manda) o una llamada
    # con identificador de llamante oculto nunca pasa por _resolve_customer,
    # asi que state.customer sigue en None hasta que need_name lo crea como
    # un dict SIN "id" (no hay fila de Customer en la base). Cualquier
    # acceso con corchetes a state.customer["id"] en vez de .get("id")
    # tiraba KeyError y hacia caer el pedido entero al confirmar.
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            assert (
                await runtime.handle_turn(
                    AgentMessageIn(message="Quiero una hamburguesa clasica", conversation_id=conversation_id)
                )
            ).status == "need_name"
            assert (
                await runtime.handle_turn(
                    AgentMessageIn(message="Carlos", conversation_id=conversation_id)
                )
            ).status == "need_fulfillment"
            assert (
                await runtime.handle_turn(
                    AgentMessageIn(message="recojo en el local", conversation_id=conversation_id)
                )
            ).status == "need_payment"
            assert (
                await runtime.handle_turn(
                    AgentMessageIn(message="efectivo", conversation_id=conversation_id)
                )
            ).status == "awaiting_confirmation"

            confirmed = await runtime.handle_turn(
                AgentMessageIn(message="confirmo", conversation_id=conversation_id)
            )
            assert confirmed.status == "closed"
            assert confirmed.order is not None
            assert confirmed.order.customer_id is None

            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.hangup_after_response is True
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_handoff_does_not_trigger_automatic_hangup():
    # Bug real evitado antes de llegar a produccion: status=="closed" se usa
    # tanto para "pedido confirmado" como para "transferido a un humano".
    # Colgar la llamada automaticamente (ver voice_agent_bridge.py) justo
    # cuando se le dice al cliente "te paso con alguien del equipo" seria
    # mucho peor que no colgar nunca -- cortarle la llamada a alguien que
    # pidio hablar con una persona.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            turn = await runtime.handle_turn(
                AgentMessageIn(message="quiero hablar con un humano", conversation_id=conversation_id)
            )
            assert turn.intent == "handoff"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "closed"
            assert state.hangup_after_response is False
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_product_search_ignores_one_letter_fragments():
    # Bug real, visto en vivo: un fragmento de transcripcion cortado ("C" de
    # "con papas fritas clasicas") es substring de casi cualquier producto
    # ("Cebolla", "Coca-Cola", "Chicha"...) y disparaba una aclaracion sin
    # sentido entre 4 productos no relacionados.
    from app.domain.services import ProductService

    async with AsyncSessionLocal() as session:
        results = await ProductService(session, settings.default_tenant_id).search_scored("C")
    assert results == []


@pytest.mark.asyncio
async def test_product_search_matches_diminutive_forms():
    # Bug real, visto en vivo: "hamburguesita"/"papitas" (diminutivos, muy
    # comunes en espanol hablado) no calzaban contra "Hamburguesa"/"Papas"
    # en el catalogo -- ni para buscar el producto ni para la pregunta de
    # menu por categoria.
    from app.domain.services import ProductService

    async with AsyncSessionLocal() as session:
        svc = ProductService(session, settings.default_tenant_id)
        burger_results = await svc.search_scored("hamburguesita")
        assert len(burger_results) == 4
        assert all("Hamburguesa" in p.name for _, p in burger_results)

        fries_results = await svc.search_scored("papitas")
        assert len(fries_results) == 2
        assert all("Papas" in p.name for _, p in fries_results)


@pytest.mark.asyncio
async def test_product_search_resolves_inka_kola_voice_aliases():
    # El cliente dice "Inka/Inca Kola", pero el ASR puede variar marca/letra
    # o juntar la frase. El catalogo debe resolver al SKU real sin pedir que
    # repita algo que si existe.
    from app.domain.services import ProductService

    async with AsyncSessionLocal() as session:
        svc = ProductService(session, settings.default_tenant_id)
        for query in ("Inka Kola", "Inca Cola", "Indocola"):
            results = await svc.search_scored(query)
            assert results
            assert results[0][1].name == "Inca Kola 500ml"


@pytest.mark.asyncio
async def test_adjacent_generic_burger_keeps_beverage_and_asks_burger_variant():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero hamburguesa chicha morada",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                    channel="phone",
                )
            )

        state = get_or_create(conversation_id, settings.default_tenant_id)
        assert turn.intent == "order.clarify"
        assert "hamburguesa prefieres" in turn.response.lower()
        assert [item.name for item in state.items] == ["Chicha Morada 500ml"]
        assert state.pending_clarification is not None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_pending_burger_clarification_wins_over_catalog_tie_for_clasica():
    # Despues de preguntar "Cual hamburguesa?", "clasica" debe resolver la
    # hamburguesa pendiente. No debe buscar "clasica" en todo el catalogo y
    # empatar contra Papas Fritas Clasicas.
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero hamburguesa chicha morada",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                    channel="phone",
                )
            )
            second = await runtime.handle_turn(
                AgentMessageIn(message="clasica", conversation_id=conversation_id, channel="phone")
            )

        state = get_or_create(conversation_id, settings.default_tenant_id)
        assert first.intent == "order.clarify"
        assert second.status == "need_name"
        assert {item.name for item in state.items} == {"Hamburguesa Clasica", "Chicha Morada 500ml"}
        assert state.pending_clarification is None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_order_summary_total_is_spoken_in_soles_for_voice_tts():
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero una Inka Kola",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                    channel="phone",
                )
            )
            await runtime.handle_turn(AgentMessageIn(message="Carlos", conversation_id=conversation_id, channel="phone"))
            await runtime.handle_turn(
                AgentMessageIn(message="recojo en el local", conversation_id=conversation_id, channel="phone")
            )
            summary = await runtime.handle_turn(
                AgentMessageIn(message="efectivo", conversation_id=conversation_id, channel="phone")
            )

        response = summary.response.lower()
        assert summary.status == "awaiting_confirmation"
        assert "s/" not in response
        assert "5 soles con 50" in response
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_menu_inquiry_recognizes_diminutive_category_word():
    # "Que bebidas tienen?" (sin intencion de pedido dentro del mensaje) debe
    # seguir siendo menu.inquiry, y con el diminutivo "bebidita" tiene que
    # reconocer la categoria igual -- antes del fix, el substring crudo no
    # calzaba "bebidita" contra la palabra clave "bebida" y devolvia el
    # menu completo en vez de solo bebidas.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            turn = await runtime.handle_turn(
                AgentMessageIn(message="Que tienen de bebidita?", conversation_id=conversation_id)
            )
        assert turn.intent == "menu.inquiry"
        response = turn.response.lower()
        assert "coca-cola" in response or "inca kola" in response
        # No debe ser el menu completo -- solo bebidas.
        assert "hamburguesa" not in response and "alfajor" not in response
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_product_search_does_not_tie_on_stopwords():
    # Bug real, visto en vivo: la transcripcion "hamburguesa de chequera"
    # (STT mal entendido) le daba a "Aros de Cebolla" el mismo puntaje que
    # a las hamburguesas reales, porque "de" hacia match EXACTO de palabra
    # completa contra el "de" de "Aros DE Cebolla" -- quedaban empatadas y
    # un acompanamiento no relacionado se colaba en la pregunta de
    # desambiguacion de hamburguesas.
    from app.domain.services import ProductService

    async with AsyncSessionLocal() as session:
        results = await ProductService(session, settings.default_tenant_id).search_scored(
            "hamburguesa de chequera"
        )
    assert results, "deberia seguir encontrando las hamburguesas por el token real 'hamburguesa'"
    assert all("Hamburguesa" in p.name for _, p in results)


@pytest.mark.asyncio
async def test_elliptical_answer_resolves_pending_clarification():
    # Bug real, visto en vivo: tras preguntar "Cual hamburguesa prefieres:
    # BBQ, Clasica, Doble, Vegetariana?", el cliente contesto "Pero te dije
    # vegetariana." -- el parser no reconoce eso como un pedido (no tiene
    # "quiero"/"una X", es una queja), asi que el agente respondia "No te
    # entendi bien" e ignoraba la pregunta pendiente, perdiendo el progreso
    # del pedido en plena llamada real.
    conversation_id = _conversation_id()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero una hamburguesa",
                    conversation_id=conversation_id,
                    customer_phone=_phone(),
                )
            )
            assert first.intent == "order.clarify"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.pending_clarification is not None
            assert state.items == []

            await runtime.handle_turn(
                AgentMessageIn(message="Pero te dije vegetariana.", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert [item.name for item in state.items] == ["Hamburguesa Vegetariana"]
            assert state.pending_clarification is None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_product_search_does_not_match_word_hidden_mid_word():
    # Bug real, visto en vivo: "cola" (el cliente pidiendo una gaseosa) es
    # substring de "chocolate" a mitad de palabra ("cho-COLA-te"), asi que
    # con un chequeo de substring sin restriccion "Volcan de Chocolate" (un
    # postre) se colaba como alternativa junto a "Coca-Cola" en una
    # pregunta de desambiguacion sin sentido -- el cliente termino sin su
    # gaseosa y con hamburguesas de mas por la confusion en cadena. El
    # match parcial solo debe valer si es PREFIJO o SUFIJO ("cola" SI es
    # sufijo real de "coca-cola" -- ese caso debe seguir funcionando).
    from app.domain.services import ProductService

    async with AsyncSessionLocal() as session:
        svc = ProductService(session, settings.default_tenant_id)

        cola_results = await svc.search_scored("cola")
        names = [p.name for _, p in cola_results]
        assert any("Coca-Cola" in name for name in names)
        assert not any("Chocolate" in name for name in names)


@pytest.mark.asyncio
async def test_rule_based_parser_does_not_mangle_yape_via_y_prefix():
    # Bug real, visto en vivo: el prefijo "y " (la palabra completa "y",
    # para frases como "una hamburguesa Y una coca cola") perdia su
    # espacio final al normalizarse, quedando en solo "y" -- eso calzaba
    # contra CUALQUIER palabra que empezara con "y", incluido "Yape" (el
    # metodo de pago). "Yape, yape." perdia las 2 primeras letras de cada
    # "Yape" y quedaba "pe", que se procesaba como si fuera un producto
    # nuevo -- duplicando la cantidad de un item ya en el pedido.
    provider = RuleBasedProvider()

    parsed = await provider.parse_message("Yape, yape.", awaiting_confirmation=False)
    assert [item.query for item in parsed.items] == ["Yape", "yape"]

    # El caso que este prefijo SI debe seguir resolviendo bien:
    parsed_y = await provider.parse_message(
        "quiero una hamburguesa y una coca cola", awaiting_confirmation=False
    )
    assert [item.query for item in parsed_y.items] == ["hamburguesa", "coca cola"]


@pytest.mark.asyncio
async def test_yape_answer_does_not_double_pending_order_quantity():
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in (
                "Quiero una hamburguesa vegetariana",
                "Carlos",
                "delivery",
                "Calle Falsa 123",
            ):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            turn = await runtime.handle_turn(
                AgentMessageIn(message="Yape, yape.", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert [item.quantity for item in state.items] == [1]
            assert "1 Hamburguesa Vegetariana" in turn.response
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_rule_based_parser_ignores_pure_filler_clause():
    # Bug real, visto en vivo: "¿Me da una hamburguesa vegetariana, por
    # favor?" separaba por comas y dejaba "por favor" como su propio
    # chunk -- "favor" sobrevive tokenize() (no es stopword) asi que se
    # buscaba como producto, perdiendo ademas el item real pedido en el
    # mismo mensaje.
    provider = RuleBasedProvider()

    parsed = await provider.parse_message(
        "Me da una hamburguesa vegetariana, por favor?", awaiting_confirmation=False
    )
    assert [item.query for item in parsed.items] == ["hamburguesa vegetariana"]
