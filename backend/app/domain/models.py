from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TenantScopedMixin, TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    industry: Mapped[str] = mapped_column(String(80), default="restaurant")
    # --- Datos del emisor para facturación electrónica SUNAT ---
    ruc: Mapped[str | None] = mapped_column(String(11))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    fiscal_address: Mapped[str | None] = mapped_column(String(300))
    apisunat_token: Mapped[str | None] = mapped_column(String(500))
    apisunat_environment: Mapped[str | None] = mapped_column(String(20), default="sandbox")


class Customer(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40), index=True)
    address: Mapped[str | None] = mapped_column(String(240))
    notes: Mapped[str | None] = mapped_column(Text)
    # --- Datos fiscales del receptor para facturacion SUNAT (catalogo 06) ---
    # "0"=Sin documento, "1"=DNI, "4"=Carnet de extranjeria, "6"=RUC,
    # "7"=Pasaporte, "A"=Cedula diplomatica. Sin valor (None) = todavia no se
    # le pidio documento a este cliente (no es lo mismo que "0" explicito).
    # NOTA: "boleta sin DNI" NO usa un doc_type especial -- API SUNAT (ver
    # invoicing_services.py) usa doc_type="1" + doc_number="99999999" como
    # placeholder, siguiendo la convencion real de apisunat.pe.
    doc_type: Mapped[str | None] = mapped_column(String(4))
    doc_number: Mapped[str | None] = mapped_column(String(20))
    # Razon social -- solo aplica si doc_type="6" (RUC, cliente empresa que
    # necesita factura). Para personas naturales (DNI) se usa `name`.
    legal_name: Mapped[str | None] = mapped_column(String(200))


class Product(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(40), default="general", index=True)
    active: Mapped[bool] = mapped_column(default=True)
    # --- Campos SUNAT para poder facturar este producto sin pedirlos cada
    # vez (ver invoicing_services.py, que arma cada linea del comprobante
    # leyendo esto). `sku` ya cumple el rol de "codigo_interno" del item, no
    # se duplica. `price` se sigue guardando CON IGV incluido (precio de
    # venta al publico, como ya lo usa el resto del sistema) -- el valor sin
    # IGV para el comprobante se calcula a partir de `igv_percentage`.
    unidad_medida: Mapped[str] = mapped_column(String(5), default="NIU")  # catalogo 03 SUNAT: NIU=unidad bienes, ZZ=unidad servicios
    igv_affectation_code: Mapped[str] = mapped_column(String(2), default="10")  # catalogo 07: 10=gravado, 20=exonerado, 21=gratuito, 30=inafecto
    igv_percentage: Mapped[float] = mapped_column(Float, default=18.0)
    igv_tribute_name: Mapped[str] = mapped_column(String(10), default="IGV")  # IGV | EXO | GRA | INA, segun igv_affectation_code


class InventoryItem(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("tenant_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship()


class Order(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    conversation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    requested_time: Mapped[str | None] = mapped_column(String(40))
    total: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(40), default="agent")
    fulfillment_type: Mapped[str | None] = mapped_column(String(20))  # delivery | pickup
    delivery_address: Mapped[str | None] = mapped_column(String(240))
    payment_method: Mapped[str | None] = mapped_column(String(20))  # efectivo | yape | plin | tarjeta
    # Codigo de aprobacion "ficticio" de Yape (ver agents/runtime.py,
    # _DETAIL_PROMPTS["yape_code"]) -- solo se llena cuando payment_method
    # == "yape". No se verifica contra ninguna API real de Yape (no la
    # tenemos integrada); se guarda tal cual para que el negocio lo cruce
    # a mano contra su propio Yape.
    payment_reference: Mapped[str | None] = mapped_column(String(20))
    # --- Aviso de WhatsApp (ver app/agents/runtime.py, _issue_invoice_and_notify) ---
    # "sent" | "failed" | "skipped_not_configured" | "skipped_no_phone". None
    # = todavia no se intento (pedido recien creado, el aviso corre en
    # paralelo fuera del turno). Se guarda para que el panel de Llamadas
    # pueda mostrar de verdad si el cliente recibio su confirmacion, en vez
    # de asumir que "se disparo" == "llego".
    whatsapp_status: Mapped[str | None] = mapped_column(String(30))
    whatsapp_sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    customer: Mapped[Customer | None] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(cascade="all, delete-orphan")


class OrderItem(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship()


class Conversation(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(80), default="sofia_demo")
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    channel: Mapped[str] = mapped_column(String(40), default="web")
    status: Mapped[str] = mapped_column(String(40), default="active")
    # Etapa real del flujo (collecting/need_name/need_fulfillment/
    # need_address/need_payment/awaiting_confirmation/closed) -- `status` de
    # arriba solo distingue activo/cerrado para no romper nada que ya lo lea
    # asi; esto es lo que el frontend usa para el flujo grafico en tiempo
    # real (ver ConversationState.status en agents/state.py).
    detail_status: Mapped[str | None] = mapped_column(String(40))
    transcript: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str | None] = mapped_column(String(80))

    customer: Mapped[Customer | None] = relationship()


class WorkflowRun(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    context_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    trace: Mapped[str] = mapped_column(Text, default="[]")


class AuditLog(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(120))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")


class VoiceTurnMetric(Base, TenantScopedMixin, TimestampMixin):
    """Observabilidad basica: cuanto tarda AgentRuntime en procesar CADA
    turno, sea chat web o llamada telefonica (via agent_llm_proxy en el
    Voice Agent bridge, o el flujo viejo de Call Control -- ambos pasan por
    AgentRuntime.handle_turn, que es donde se mide). No mide STT/TTS (eso lo
    corre Deepgram fuera de nuestro proceso, sin visibilidad nuestra) --
    mide el tramo que SI controlamos: el "pensar" (nuestra logica + la
    llamada a Gemini cuando aplica). Es la pieza que hoy realmente podiamos
    instrumentar sin agregar infraestructura nueva."""

    __tablename__ = "voice_turn_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(120), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    intent: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    think_ms: Mapped[int] = mapped_column(Integer)
    used_fallback: Mapped[bool] = mapped_column(default=False)
