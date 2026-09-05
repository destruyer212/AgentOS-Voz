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
            assert "en bebidas tenemos" in second.response.lower()
            assert "cuál prefieres" in second.response.lower()
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
                    AgentMessageIn(message="Av Siempre Viva 123, Comas", conversation_id=conversation_id)
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
async def test_product_search_resolves_mostro_misheard_as_monstruo():
    # Bug real, visto en vivo: el cliente pidio "Mostro Olivar" (chaufa del
    # menu) y el ASR lo transcribio como "monstruo olivar" -- "mostro" no
    # es palabra comun, el modelo de lenguaje del STT se va hacia
    # "monstruo" (mucho mas frecuente). Sin el alias, "olivar" solo
    # calzaba con OTROS productos de otras categorias, nunca con el
    # chaufa real que se acababa de nombrar.
    from app.domain.services import ProductService

    async with AsyncSessionLocal() as session:
        product = Product(
            tenant_id=settings.default_tenant_id, sku="TEST-MOSTRO-OLV", name="Mostro Olivar",
            price=25.0, category="chaufa",
        )
        session.add(product)
        await session.flush()
        session.add(InventoryItem(tenant_id=settings.default_tenant_id, product_id=product.id, quantity=100))
        await session.commit()

    async with AsyncSessionLocal() as session:
        svc = ProductService(session, settings.default_tenant_id)
        for query in ("monstruo olivar", "el monstruo"):
            results = await svc.search_scored(query)
            assert results
            assert results[0][1].name == "Mostro Olivar"


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
            await runtime.handle_turn(
                AgentMessageIn(message="efectivo", conversation_id=conversation_id, channel="phone")
            )
            # En telefono, despues del pago se pregunta boleta/factura + el
            # DNI de 8 digitos (pedido explicito del negocio) antes del
            # resumen final -- ver _next_missing_detail.
            await runtime.handle_turn(
                AgentMessageIn(message="boleta", conversation_id=conversation_id, channel="phone")
            )
            summary = await runtime.handle_turn(
                AgentMessageIn(message="12345678", conversation_id=conversation_id, channel="phone")
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
                "Calle Falsa 123, Los Olivos",
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


@pytest.mark.asyncio
async def test_rule_based_parser_recognizes_tiene_as_menu_question():
    # Bug real, visto en vivo: "¿Tiene parrilla?" (forma "usted") no
    # calzaba como pregunta de menu -- solo "tienen"/"tienes" estaban
    # cubiertas. "parrilla" se trataba como un producto ambiguo a medio
    # pedir y la respuesta salia rota ("¿Cual ¿Tiene parrilla? prefieres...").
    provider = RuleBasedProvider()

    parsed = await provider.parse_message("¿Tiene parrilla?", awaiting_confirmation=False)
    assert parsed.intent == "menu.inquiry"
    assert parsed.items == []


@pytest.mark.asyncio
async def test_generic_acknowledgment_during_detail_collection_repeats_question_instead_of_searching():
    # Bug real, visto en vivo: "Perfecto." solo (sin contenido real) dicho
    # mientras se pedia el metodo de pago no calzaba como pago valido y
    # caia al parser de items -- se buscaba como si fuera un producto
    # ("No encontré Perfecto en el menú"), perdiendo la pregunta pendiente.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in (
                "Quiero una hamburguesa vegetariana",
                "Carlos",
                "delivery",
                "Calle Falsa 123, Los Olivos",
            ):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            turn = await runtime.handle_turn(
                AgentMessageIn(message="Perfecto.", conversation_id=conversation_id)
            )
            assert turn.status == "need_payment"
            assert "no encontr" not in turn.response.lower()
            assert "efectivo" in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_pending_clarification_survives_a_fragment_that_does_not_resolve_it():
    # Bug real, visto en vivo: tras "Cual gaseosa prefieres: A, B, C?", un
    # fragmento cortado por el STT ("Una de") no calzaba con ninguna
    # opcion Y ademas el parser lo clasificaba como "smalltalk" (no
    # "order.create"/"order.modify"), asi que el intento de resolver la
    # aclaracion pendiente ni se ejecutaba -- el agente respondia un
    # generico "Dime que te provoca pedir hoy?", perdiendo la pregunta
    # pendiente por completo.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            first = await runtime.handle_turn(
                AgentMessageIn(message="Quiero una hamburguesa", conversation_id=conversation_id, channel="phone")
            )
            assert first.intent == "order.clarify"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.pending_clarification is not None

            turn = await runtime.handle_turn(
                AgentMessageIn(message="Una de", conversation_id=conversation_id, channel="phone")
            )
            assert "Cuál hamburguesa" in turn.response or "Cual hamburguesa" in turn.response
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.pending_clarification is not None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_hours_inquiry_answers_with_real_time_not_nlu():
    # "¿Atienden hoy?"/"¿hasta que hora abren?" tiene que responderse con la
    # hora real del servidor (ver app/domain/business_hours.py), sin pasar
    # por el parser de pedidos -- nunca debe salir "No encontré ... en el
    # menú" para esto.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            turn = await runtime.handle_turn(
                AgentMessageIn(message="¿Hasta qué hora atienden hoy?", conversation_id=conversation_id)
            )
            assert turn.intent == "hours.inquiry"
            assert "no encontr" not in turn.response.lower()
            assert "23:00" in turn.response or "12:00" in turn.response
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_hours_inquiry_mid_detail_collection_repeats_pending_question():
    # Si te preguntan por el horario a mitad de dar los datos del pedido
    # (ej. mientras se pide el metodo de pago), hay que responder Y repetir
    # la pregunta pendiente -- no perder el hilo del pedido.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa vegetariana", "Carlos", "delivery", "Calle Falsa 123, Los Olivos"):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            turn = await runtime.handle_turn(
                AgentMessageIn(message="¿Y hasta qué hora abren?", conversation_id=conversation_id)
            )
            assert turn.intent == "hours.inquiry"
            assert "efectivo" in turn.response.lower()  # repite la pregunta de pago
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_payment"  # el pedido sigue donde estaba
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_bare_confirm_word_outside_confirmation_is_not_a_product_search():
    # Bug real, visto en vivo: "Sí." solo, dicho SIN que hubiera una
    # pregunta de confirmacion pendiente (ej. el cliente repitiendo algo
    # que dijo el agente), caia al parser de items y se buscaba como
    # producto ("No encontré Sí en el menú").
    provider = RuleBasedProvider()
    for message in ("Sí.", "No."):
        parsed = await provider.parse_message(message, awaiting_confirmation=False)
        assert parsed.intent == "smalltalk"
        assert parsed.items == []

    # Con una confirmacion de verdad pendiente, debe seguir funcionando.
    parsed = await provider.parse_message("Sí.", awaiting_confirmation=True)
    assert parsed.intent == "order.confirm"
    assert parsed.confirms is True


@pytest.mark.asyncio
async def test_pending_clarification_resolves_even_when_followup_parses_as_order_create():
    # Bug real, visto en vivo (llamada real, El Olivar Grill): tras
    # preguntar "Cual hamburguesa prefieres: Clasica, Doble, BBQ,
    # Vegetariana?", la respuesta del cliente ("Quiero la BBQ") parsea
    # como order.create (empieza con "Quiero"), NO como una respuesta a
    # la aclaracion -- eso saltaba la logica de desambiguacion, volvia a
    # buscar "la BBQ" desde cero, no encontraba nada exacto y repetia LA
    # MISMA pregunta con las 4 opciones otra vez, sin avanzar nunca.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(message="Quiero una hamburguesa", conversation_id=conversation_id, channel="web")
            )
            assert "prefieres" in first.response.lower()  # ambiguo, pregunto

            second = await runtime.handle_turn(
                AgentMessageIn(message="Quiero la BBQ", conversation_id=conversation_id, channel="web")
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert [item.name for item in state.items] == ["Hamburguesa BBQ"]
            assert "prefieres" not in second.response.lower()  # NO debe repetir la pregunta
            assert state.pending_clarification is None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_spoken_fraction_words_resolve_against_numeric_catalog_names():
    # Bug real, visto en vivo: el catalogo real de El Olivar guarda las
    # fracciones en numero ("1/2 Pollo a la Brasa", "1/4 de Pollo a la
    # Brasa"), pero el cliente las dice con palabras ("un cuarto de pollo
    # a la brasa del menu"). Sin normalizar, esa frase nunca matcheaba
    # NINGUNA opcion por nombre exacto y el agente repetia la pregunta de
    # aclaracion con las 4 variantes una y otra vez, sin poder avanzar.
    conversation_id = _conversation_id()
    async with AsyncSessionLocal() as session:
        for sku, name, price in (
            ("TEST-POL-MED", "1/2 Pollo a la Brasa", 39.5),
            ("TEST-POL-CUA", "1/4 de Pollo a la Brasa", 21.5),
            ("TEST-POL-CUA-ANT", "1/4 de Pollo a la Brasa El Olivar + Anticucho", 28.0),
            ("TEST-POL-MEN", "Menu 1/4 de Pollo a la Brasa", 21.0),
        ):
            product = Product(
                tenant_id=settings.default_tenant_id, sku=sku, name=name, price=price, category="pollo_brasa"
            )
            session.add(product)
            await session.flush()
            session.add(InventoryItem(tenant_id=settings.default_tenant_id, product_id=product.id, quantity=100))
        await session.commit()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            # Sin normalizar, "un cuarto de pollo a la brasa" no matcheaba
            # NADA por nombre exacto y caia en el listado ambiguo completo.
            # Normalizado a "1/4 de pollo a la brasa", matchea EXACTO contra
            # "1/4 de Pollo a la Brasa" -- ni siquiera hace falta preguntar.
            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero un cuarto de pollo a la brasa", conversation_id=conversation_id, channel="web"
                )
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert [item.name for item in state.items] == ["1/4 de Pollo a la Brasa"]
            assert "prefieres" not in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_yape_misheard_as_yate_still_resolves_as_payment():
    # Bug real, visto en vivo: el ASR transcribio "Pago con Yape" como
    # "Pago con yate" (barco) -- fonéticamente muy parecido por telefono.
    # Sin el alias, caia a la busqueda de productos ("No encontre Pago con
    # yate en el menu") en vez de reconocerse como forma de pago, dejando
    # al cliente atascado en el mismo paso.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            for message in ("Quiero una hamburguesa clasica", "Carlos", "en el local"):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_payment"

            turn = await runtime.handle_turn(
                AgentMessageIn(message="Pago con yate.", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.payment_method == "yape"
            assert "no encontré" not in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_pli_recognized_as_plin_but_not_inside_other_words():
    # "pli" recortado (mismo motivo que "yate" arriba) debe reconocerse
    # como Plin -- pero con limite de palabra, para no matchear "pli"
    # adentro de "explicar"/"cumplir" y confundir eso con una respuesta
    # de pago.
    from app.agents.runtime import _match_payment

    assert _match_payment("pago con pli") == "plin"
    assert _match_payment("pli") == "plin"
    assert _match_payment("me puedes explicar las opciones de pago") is None
    assert _match_payment("necesito cumplir con el pedido") is None


@pytest.mark.asyncio
async def test_pli_misheard_plin_resolves_as_payment_end_to_end():
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            for message in ("Quiero una hamburguesa clasica", "Carlos", "en el local"):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_payment"

            turn = await runtime.handle_turn(
                AgentMessageIn(message="Pago con pli.", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.payment_method == "plin"
            assert "no encontré" not in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_two_ambiguous_fragments_in_same_message_ask_only_one_question():
    # Bug real, visto en vivo (llamada de produccion): "Quiero un cuarto de
    # pollo, el olivar." trae DOS fragmentos ambiguos en el mismo mensaje
    # ("cuarto de pollo" matchea 4 variantes; "el olivar" matchea otros 4
    # productos distintos que tienen "Olivar" en el nombre). Sin proteccion,
    # el agente generaba DOS preguntas de aclaracion y las pegaba en una
    # sola respuesta confusa ("Cual cuarto de pollo prefieres...? Cual
    # olivar prefieres...?"), y la segunda pisaba el pending_clarification
    # de la primera -- resultado: loop, nunca se podia avanzar.
    conversation_id = _conversation_id()
    async with AsyncSessionLocal() as session:
        for sku, name, price, category in (
            ("TEST-POL-CUA3", "1/4 de Pollo a la Brasa", 21.5, "pollo_brasa"),
            ("TEST-POL-CUA-ANT3", "1/4 de Pollo a la Brasa El Olivar + Anticucho", 28.0, "pollo_brasa"),
            ("TEST-FET-HUA3", "Fetuccini a la Huancaina con 1/4 de Pollo", 26.0, "pasta"),
            ("TEST-FET-ALF3", "Fetuccini a lo Alfredo con 1/4 de Pollo", 28.5, "pasta"),
            ("TEST-ENS-OLI3", "Ensalada El Olivar", 15.0, "ensalada"),
            ("TEST-HUA-OLI3", "Huayrito El Olivar", 26.0, "pollo_brasa"),
            ("TEST-MEN-OLI3", "Menu Pollo El Olivar", 22.5, "menu"),
        ):
            product = Product(tenant_id=settings.default_tenant_id, sku=sku, name=name, price=price, category=category)
            session.add(product)
            await session.flush()
            session.add(InventoryItem(tenant_id=settings.default_tenant_id, product_id=product.id, quantity=100))
        await session.commit()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero un cuarto de pollo, el olivar", conversation_id=conversation_id, channel="web"
                )
            )
            # Solo UNA pregunta de aclaracion, no dos pegadas.
            assert turn.response.lower().count("prefieres") == 1
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_trailing_fragment_after_resolved_clarification_is_not_a_new_search():
    # Bug real, visto en vivo (llamada real): tras "¿Cual cuarto de pollo
    # prefieres: ... El Olivar + Anticucho ...?", el cliente contesto
    # "un cuarto de pollo con anticucho, el olivar." -- el parser separa
    # esto en DOS items: el primero ("...con anticucho") resuelve bien
    # contra la aclaracion pendiente, pero el segundo ("el olivar", la
    # cola de la MISMA frase) se buscaba de cero como si fuera OTRO
    # producto, encontraba varios "El Olivar" sueltos sin relacion
    # (ensalada, menu) y pisaba lo que ya se habia resuelto bien con una
    # pregunta nueva -- el cliente sentia que nunca se le entendia nada.
    conversation_id = _conversation_id()
    async with AsyncSessionLocal() as session:
        for sku, name, price in (
            ("TEST-POL-CUA2", "1/4 de Pollo a la Brasa", 21.5),
            ("TEST-POL-CUA-ANT2", "1/4 de Pollo a la Brasa El Olivar + Anticucho", 28.0),
            ("TEST-FET-HUA2", "Fetuccini a la Huancaina con 1/4 de Pollo", 26.0),
            ("TEST-FET-ALF2", "Fetuccini a lo Alfredo con 1/4 de Pollo", 28.5),
            ("TEST-ENS-OLV2", "Ensalada El Olivar", 15.0),
        ):
            product = Product(
                tenant_id=settings.default_tenant_id, sku=sku, name=name, price=price, category="pollo_brasa"
            )
            session.add(product)
            await session.flush()
            session.add(InventoryItem(tenant_id=settings.default_tenant_id, product_id=product.id, quantity=100))
        await session.commit()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(message="Quiero un cuarto de pollo.", conversation_id=conversation_id, channel="web")
            )
            assert "prefieres" in first.response.lower()

            second = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero un cuarto de pollo con anticucho, el olivar.",
                    conversation_id=conversation_id,
                    channel="web",
                )
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert [item.name for item in state.items] == ["1/4 de Pollo a la Brasa El Olivar + Anticucho"]
            assert "prefieres" not in second.response.lower()  # NO debe volver a preguntar nada
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_question_mark_phrase_is_never_accepted_as_customer_name():
    # Bug real, visto en vivo: en una llamada telefonica, el nombre del
    # cliente quedo guardado literal como "¿Puede repetir?" (una frase de
    # pregunta, no un nombre real -- probablemente la propia voz del agente
    # mal etiquetada como turno del cliente por el STT). Paso el chequeo de
    # "1 a 4 palabras sin digitos" sin problema y termino en la confirmacion
    # del pedido y hasta en el mensaje real de WhatsApp. Un nombre de verdad
    # nunca lleva "?"/"¿".
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero una hamburguesa clasica", conversation_id=conversation_id, channel="web"
                )
            )
            assert first.status == "need_name"

            await runtime.handle_turn(
                AgentMessageIn(message="¿Puede repetir?", conversation_id=conversation_id, channel="web")
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_name"  # no avanzo con un nombre invalido
            name = (state.customer or {}).get("name")
            assert name in (None, "Cliente telefonico")  # nunca la pregunta literal
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_name_correction_during_confirmation_updates_summary_instead_of_searching_menu():
    # Bug real, visto en vivo: el resumen final mostro un nombre mal
    # capturado ("A nombre de ¿Puede repetir?. ¿Confirmas?") y el cliente
    # intento corregirlo ("Dayana.", "Mi nombre es", "Mi nombre es
    # Dayana.") -- cada intento se buscaba como producto ("No encontre
    # Dayana en el menu") en vez de reconocerse como correccion de nombre,
    # y el resumen seguia mostrando el nombre viejo para siempre.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            for message in ("Quiero una hamburguesa clasica", "Carlos", "en el local", "efectivo"):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "awaiting_confirmation"
            assert state.customer["name"] == "Carlos"

            turn = await runtime.handle_turn(
                AgentMessageIn(message="Mi nombre es Dayana.", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.customer["name"] == "Dayana"
            assert state.status == "awaiting_confirmation"  # sigue esperando confirmar, con el nombre ya corregido
            assert "no encontré" not in turn.response.lower()
            assert "dayana" in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_partial_item_success_is_confirmed_not_silent():
    # Bug real, visto en vivo: "Salvan negro y torta de chocolate." (STT
    # garbled "Selva Negra") -- "torta de chocolate" SI se agregaba, pero
    # la respuesta solo decia "No encontre Salvan negro", nunca mencionaba
    # lo que si entro. El cliente, sin saber que ya se habia agregado,
    # repetia la frase completa en el turno siguiente y terminaba con
    # "Torta de Chocolate" duplicada en el pedido (2 en vez de 1).
    conversation_id = _conversation_id()
    async with AsyncSessionLocal() as session:
        for sku, name, price in (
            ("TEST-TORTA-CHOC", "Torta de Chocolate", 9.0),
            ("TEST-SELVA-NEGRA", "Selva Negra", 9.0),
        ):
            product = Product(
                tenant_id=settings.default_tenant_id, sku=sku, name=name, price=price, category="postre"
            )
            session.add(product)
            await session.flush()
            session.add(InventoryItem(tenant_id=settings.default_tenant_id, product_id=product.id, quantity=100))
        await session.commit()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero Salvan negro y torta de chocolate.",
                    conversation_id=conversation_id,
                    channel="web",
                )
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            # Se agrego SOLO 1 Torta de Chocolate -- no la duplico.
            assert [(i.name, i.quantity) for i in state.items] == [("Torta de Chocolate", 1)]
            # Y la respuesta lo confirma en vez de quedarse callada.
            assert "torta de chocolate" in turn.response.lower()
            assert "no encontré" in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_please_repeat_during_pending_clarification_repeats_it_not_a_product_search():
    # Bug real, visto en vivo: con una aclaracion pendiente ("Cual cuarto
    # de pollo prefieres...?"), el cliente dijo "¿Puede repetir, por
    # favor?" -- eso parseaba como order.create (no como smalltalk), asi
    # que se buscaba como PRODUCTO ("No encontre ¿Puede repetir en el
    # menu") y se perdia la pregunta pendiente por completo.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            first = await runtime.handle_turn(
                AgentMessageIn(message="Quiero una hamburguesa", conversation_id=conversation_id, channel="web")
            )
            assert "prefieres" in first.response.lower()

            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="¿Puede repetir, por favor?", conversation_id=conversation_id, channel="web"
                )
            )
            assert "no encontré" not in turn.response.lower()
            assert "prefieres" in turn.response.lower()  # repite la MISMA pregunta
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_spoken_mas_resolves_against_catalog_plus_sign():
    # Bug real, visto en vivo: el cliente dijo "un cuarto de pollo, el
    # olivar mas anticucho" para pedir "1/4 de Pollo a la Brasa El Olivar
    # + Anticucho" -- "mas" (como lo dice el cliente) nunca calzaba con
    # "+" (como esta en el catalogo), asi que la aclaracion no se
    # resolvia nunca con esa frase.
    # Nombres unicos (no "1/4 de Pollo a la Brasa" a secas -- ese nombre lo
    # reusan varios tests de este archivo en la misma test_agentos.db
    # compartida, y con 4+ copias duplicadas el candidates[:4] de la
    # busqueda ya no trae la variante Olivar+Anticucho adentro).
    conversation_id = _conversation_id()
    async with AsyncSessionLocal() as session:
        for sku, name, price in (
            ("TEST-COSTQA5", "1/4 de Costilla QA5", 21.5),
            ("TEST-COSTQA5-ANT", "1/4 de Costilla QA5 El Olivar + Anticucho", 28.0),
        ):
            product = Product(
                tenant_id=settings.default_tenant_id, sku=sku, name=name, price=price, category="pollo_brasa"
            )
            session.add(product)
            await session.flush()
            session.add(InventoryItem(tenant_id=settings.default_tenant_id, product_id=product.id, quantity=100))
        await session.commit()

    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            # Sin "QA5" en lo que dice el cliente a proposito: asi ninguna
            # de las 2 opciones matchea exacto y sigue siendo ambigua.
            first = await runtime.handle_turn(
                AgentMessageIn(
                    message="Quiero un cuarto de costilla.", conversation_id=conversation_id, channel="web"
                )
            )
            assert "prefieres" in first.response.lower()

            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="El olivar mas anticucho.", conversation_id=conversation_id, channel="web"
                )
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert [item.name for item in state.items] == ["1/4 de Costilla QA5 El Olivar + Anticucho"]
            assert "prefieres" not in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_delivery_rejects_out_of_zone_address_then_accepts_a_nearby_one():
    # Pedido explicito del negocio: delivery solo cerca de Puente Piedra.
    # Una direccion fuera de zona no debe guardarse ni pasar a la siguiente
    # pregunta -- tiene que repetir explicando el limite, no el generico
    # "cual es la direccion".
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            for message in ("Quiero una hamburguesa clasica", "Carlos", "delivery"):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            rejected = await runtime.handle_turn(
                AgentMessageIn(message="Av. Larco 123, Miraflores", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_address"  # no avanzo
            assert state.delivery_address is None
            assert "Puente Piedra" in rejected.response

            accepted = await runtime.handle_turn(
                AgentMessageIn(message="Jr. Los Alamos 456, Comas", conversation_id=conversation_id)
            )
            assert accepted.status == "need_payment"  # esta vez si avanzo
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.delivery_address == "Jr. Los Alamos 456, Comas"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_delivery_fee_charged_only_on_delivery_not_pickup():
    # El cobro del motorizado (S/10 por defecto) tiene que aparecer en el
    # resumen hablado Y en el pedido real cuando es delivery, y no
    # aparecer para nada cuando es recojo en el local.
    delivery_id = _conversation_id()
    pickup_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in (
                "Quiero una hamburguesa clasica", "Carlos", "delivery",
                "Jr. Los Alamos 456, Comas", "efectivo",
            ):
                turn = await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=delivery_id))
            assert "Delivery" in turn.response  # resumen final, antes de "Confirmas?"

            confirm = await runtime.handle_turn(AgentMessageIn(message="Sí, confirmo", conversation_id=delivery_id))
            assert {item.product_name for item in confirm.order.items} >= {"Hamburguesa Clasica", "Delivery"}
            assert confirm.order.total == 12.90 + settings.delivery_fee_soles

        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo"):
                turn = await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=pickup_id))
            assert "Delivery" not in turn.response

            confirm = await runtime.handle_turn(AgentMessageIn(message="Sí, confirmo", conversation_id=pickup_id))
            assert {item.product_name for item in confirm.order.items} == {"Hamburguesa Clasica"}
            assert confirm.order.total == 12.90
    finally:
        reset(delivery_id)
        reset(pickup_id)


@pytest.mark.asyncio
async def test_delivery_asks_district_explicitly_when_address_does_not_name_one():
    # Ni la llamada ni el WhatsApp piden "direccion" y "distrito" como dos
    # preguntas separadas de entrada -- pero si la direccion que dan no
    # menciona ningun distrito, no se puede saber si esta en zona. En vez
    # de dejarla pasar en silencio, se pregunta el distrito una vez mas.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            for message in ("Quiero una hamburguesa clasica", "Carlos", "delivery"):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            # Direccion sin distrito: no se guarda, se pregunta el distrito.
            asked = await runtime.handle_turn(
                AgentMessageIn(message="Jr. Los Alamos 456", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_address"
            assert state.delivery_address is None
            assert "distrito" in asked.response.lower()

            # El distrito solo (una palabra) se junta con la calle ya dada.
            accepted = await runtime.handle_turn(
                AgentMessageIn(message="Comas", conversation_id=conversation_id)
            )
            assert accepted.status == "need_payment"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.delivery_address == "Jr. Los Alamos 456, Comas"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_delivery_district_answer_rejects_if_out_of_zone():
    # Si tras preguntar el distrito la respuesta esta fuera de zona, se
    # rechaza igual que una direccion completa fuera de zona desde el
    # principio -- no se cuela por haber pasado por la pregunta extra.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            for message in ("Quiero una hamburguesa clasica", "Carlos", "delivery"):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            asked = await runtime.handle_turn(
                AgentMessageIn(message="Av. Larco 123", conversation_id=conversation_id)
            )
            assert "distrito" in asked.response.lower()

            rejected = await runtime.handle_turn(
                AgentMessageIn(message="Miraflores", conversation_id=conversation_id)
            )
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.status == "need_address"
            assert state.delivery_address is None
            assert "Puente Piedra" in rejected.response
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_delivery_gives_up_asking_district_after_one_retry_to_avoid_a_loop():
    # Si ni siquiera la segunda respuesta trae un distrito reconocible, no
    # se vuelve a preguntar en loop -- se deja pasar tal cual (mejor no
    # trabar a un cliente real de la zona por no saber nombrar su distrito).
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)

            for message in ("Quiero una hamburguesa clasica", "Carlos", "delivery"):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            asked = await runtime.handle_turn(
                AgentMessageIn(message="Jr. Los Alamos 456", conversation_id=conversation_id)
            )
            assert "distrito" in asked.response.lower()

            turn = await runtime.handle_turn(
                AgentMessageIn(message="cerca del parque", conversation_id=conversation_id)
            )
            assert turn.status == "need_payment"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.delivery_address == "Jr. Los Alamos 456, cerca del parque"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_boleta_by_default_does_not_ask_for_ruc():
    # El caso comun: nadie pide factura, asi que el pedido llega derecho a
    # la confirmacion sin ninguna pregunta nueva -- la boleta se arma sola
    # al confirmar (ver AgentRuntime._issue_invoice_and_notify).
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            turn = None
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo"):
                turn = await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))
            assert turn.status == "awaiting_confirmation"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.wants_factura is False
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_factura_request_during_collection_adds_ruc_question_before_confirmation():
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in (
                "Necesito factura", "Quiero una hamburguesa clasica", "Carlos",
                "recojo en el local", "efectivo",
            ):
                turn = await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))
            assert turn.status == "need_ruc"
            assert "RUC" in turn.response

            confirmed = await runtime.handle_turn(
                AgentMessageIn(
                    message="el RUC es 20123456789, razon social Comercial Prueba SAC",
                    conversation_id=conversation_id,
                )
            )
            assert confirmed.status == "awaiting_confirmation"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.factura_ruc == "20123456789"
            assert "comercial prueba sac" in state.factura_razon_social.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_factura_request_after_summary_shown_asks_ruc_then_reshows_summary():
    # Bug real que se queria evitar: si el cliente pide factura DESPUES de
    # ya haber escuchado el resumen final, no puede confirmarse la boleta a
    # medias -- hay que interrumpir, pedir el RUC, y volver a mostrar el
    # resumen antes de aceptar un "si, confirmo" real.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            summary = None
            for message in (
                "Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo",
            ):
                summary = await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))
            assert summary.status == "awaiting_confirmation"

            asked = await runtime.handle_turn(
                AgentMessageIn(message="espera, necesito factura", conversation_id=conversation_id)
            )
            assert asked.status == "need_ruc"

            resummarized = await runtime.handle_turn(
                AgentMessageIn(message="20123456789 Comercial Prueba SAC", conversation_id=conversation_id)
            )
            assert resummarized.status == "awaiting_confirmation"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_invalid_ruc_repeats_the_question():
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in (
                "Necesito factura", "Quiero una hamburguesa clasica", "Carlos",
                "recojo en el local", "efectivo",
            ):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            rejected = await runtime.handle_turn(
                AgentMessageIn(message="mi ruc es 12345", conversation_id=conversation_id)
            )
            assert rejected.status == "need_ruc"
            assert "no reconocí" in rejected.response.lower()
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.factura_ruc is None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_customer_changes_mind_back_to_boleta_while_at_need_ruc():
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in (
                "Necesito factura", "Quiero una hamburguesa clasica", "Carlos",
                "recojo en el local", "efectivo",
            ):
                await runtime.handle_turn(AgentMessageIn(message=message, conversation_id=conversation_id))

            switched = await runtime.handle_turn(
                AgentMessageIn(message="mejor boleta nomás", conversation_id=conversation_id)
            )
            assert switched.status == "awaiting_confirmation"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.wants_factura is False
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_phone_call_asks_boleta_or_factura_before_confirmation():
    # Pedido explicito del negocio: en la voz (nunca en web/WhatsApp) se
    # pregunta boleta o factura antes de confirmar, sin importar si el
    # cliente pidio factura por su cuenta o no.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            turn = None
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo"):
                turn = await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="phone")
                )
            assert turn.status == "need_document"
            assert "boleta" in turn.response.lower() and "factura" in turn.response.lower()
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_phone_call_boleta_requires_exact_8_digit_dni():
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo"):
                await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="phone")
                )

            asked_dni = await runtime.handle_turn(
                AgentMessageIn(message="boleta", conversation_id=conversation_id, channel="phone")
            )
            assert asked_dni.status == "need_dni"

            rejected = await runtime.handle_turn(
                AgentMessageIn(message="mi dni es 1234", conversation_id=conversation_id, channel="phone")
            )
            assert rejected.status == "need_dni"
            assert "8 dígitos" in rejected.response or "dni" in rejected.response.lower()

            accepted = await runtime.handle_turn(
                AgentMessageIn(message="45678912", conversation_id=conversation_id, channel="phone")
            )
            assert accepted.status == "awaiting_confirmation"
            assert "45678912" in accepted.response
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.boleta_dni == "45678912"
            assert state.invoice_document_type == "boleta"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_phone_call_factura_requires_exact_11_digit_ruc():
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo"):
                await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="phone")
                )

            asked_ruc = await runtime.handle_turn(
                AgentMessageIn(message="factura", conversation_id=conversation_id, channel="phone")
            )
            assert asked_ruc.status == "need_ruc"

            rejected = await runtime.handle_turn(
                AgentMessageIn(message="mi ruc es 123", conversation_id=conversation_id, channel="phone")
            )
            assert rejected.status == "need_ruc"

            accepted = await runtime.handle_turn(
                AgentMessageIn(message="20123456789", conversation_id=conversation_id, channel="phone")
            )
            assert accepted.status == "awaiting_confirmation"
            assert "20123456789" in accepted.response
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.factura_ruc == "20123456789"
            assert state.invoice_document_type == "factura"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_phone_call_can_give_document_type_and_dni_in_one_breath():
    # Respuesta natural por voz: "boleta, 45678912" en un solo turno en vez
    # de dos preguntas separadas.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo"):
                await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="phone")
                )

            turn = await runtime.handle_turn(
                AgentMessageIn(message="boleta, 45678912", conversation_id=conversation_id, channel="phone")
            )
            assert turn.status == "awaiting_confirmation"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.boleta_dni == "45678912"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_web_channel_never_asks_for_document_type_or_dni():
    # Solo la voz exige boleta/factura + DNI/RUC obligatorio -- web y
    # WhatsApp mantienen el comportamiento historico (boleta automatica).
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            turn = None
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo"):
                turn = await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="web")
                )
            assert turn.status == "awaiting_confirmation"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.invoice_document_type is None
            assert state.boleta_dni is None
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_boleto_is_understood_as_boleta():
    # Bug real, visto en vivo: el STT transcribio "Boleta" como "Boleto"
    # (palabra real y mucho mas comun) -- el cliente tuvo que repetirlo.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo"):
                await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="phone")
                )
            turn = await runtime.handle_turn(
                AgentMessageIn(message="Boleto.", conversation_id=conversation_id, channel="phone")
            )
            assert turn.status == "need_dni"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_dni_recognized_from_grouped_spoken_numbers():
    # Bug real, visto en vivo: una llamada real termino colgada porque el
    # cliente dicto su DNI en grupos de dos digitos, como se hace
    # normalmente por telefono en Peru -- "Setenta, ochenta y uno, treinta
    # y uno, cincuenta y dos" (70-81-31-52 -> DNI 70813152). El regex viejo
    # solo buscaba digitos ya escritos (0-9), nunca reconocia numeros
    # dichos en palabras, y la llamada quedo pidiendo el DNI en loop hasta
    # que colgaron sin completar el pedido.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo", "boleta"):
                await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="phone")
                )
            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Setenta, ochenta y uno, treinta y uno, cincuenta y dos.",
                    conversation_id=conversation_id, channel="phone",
                )
            )
            assert turn.status == "awaiting_confirmation"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.boleta_dni == "70813152"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_dni_recognized_from_individually_spoken_digits():
    # Mismo DNI real (70813152) que el test anterior, pero dictado digito
    # por digito -- la otra forma en que la misma llamada real lo intento
    # decir despues de que el primer intento fallara.
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo", "boleta"):
                await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="phone")
                )
            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Siete cero ocho uno tres uno cinco dos.",
                    conversation_id=conversation_id, channel="phone",
                )
            )
            assert turn.status == "awaiting_confirmation"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.boleta_dni == "70813152"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_ruc_recognized_from_spoken_numbers():
    conversation_id = _conversation_id()
    try:
        async with AsyncSessionLocal() as session:
            runtime = AgentRuntime(session, settings.default_tenant_id)
            for message in ("Quiero una hamburguesa clasica", "Carlos", "recojo en el local", "efectivo", "factura"):
                await runtime.handle_turn(
                    AgentMessageIn(message=message, conversation_id=conversation_id, channel="phone")
                )
            # 20601234567 dicho en grupos de dos.
            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="veinte, sesenta, doce, treinta y cuatro, cincuenta y seis, siete.",
                    conversation_id=conversation_id, channel="phone",
                )
            )
            assert turn.status == "awaiting_confirmation"
            state = get_or_create(conversation_id, settings.default_tenant_id)
            assert state.factura_ruc == "20601234567"
    finally:
        reset(conversation_id)
