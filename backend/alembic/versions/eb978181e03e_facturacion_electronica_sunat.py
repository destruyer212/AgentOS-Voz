"""facturacion electronica sunat

Agrega los campos fiscales (RUC/DNI, unidad de medida, afectacion IGV) a
tenants/customers/products y las tablas nuevas de comprobantes electronicos
(invoice_series, invoices, invoice_items). Ver app/domain/invoicing_models.py
y app/domain/invoicing_services.py.

Revision ID: eb978181e03e
Revises: 647cfc5a8aae
Create Date: 2026-09-05 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'eb978181e03e'
down_revision: str | Sequence[str] | None = '647cfc5a8aae'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- Datos del emisor (tenant) para facturacion SUNAT ---
    op.add_column('tenants', sa.Column('ruc', sa.String(length=11), nullable=True))
    op.add_column('tenants', sa.Column('legal_name', sa.String(length=200), nullable=True))
    op.add_column('tenants', sa.Column('fiscal_address', sa.String(length=300), nullable=True))
    op.add_column('tenants', sa.Column('apisunat_token', sa.String(length=500), nullable=True))
    op.add_column(
        'tenants',
        sa.Column('apisunat_environment', sa.String(length=20), nullable=True, server_default='sandbox'),
    )

    # --- Datos fiscales del receptor (customer) ---
    op.add_column('customers', sa.Column('doc_type', sa.String(length=4), nullable=True))
    op.add_column('customers', sa.Column('doc_number', sa.String(length=20), nullable=True))
    op.add_column('customers', sa.Column('legal_name', sa.String(length=200), nullable=True))

    # --- Campos SUNAT por producto ---
    op.add_column(
        'products',
        sa.Column('unidad_medida', sa.String(length=5), nullable=False, server_default='NIU'),
    )
    op.add_column(
        'products',
        sa.Column('igv_affectation_code', sa.String(length=2), nullable=False, server_default='10'),
    )
    op.add_column(
        'products',
        sa.Column('igv_percentage', sa.Float(), nullable=False, server_default='18.0'),
    )
    op.add_column(
        'products',
        sa.Column('igv_tribute_name', sa.String(length=10), nullable=False, server_default='IGV'),
    )

    # --- Series y correlativos de comprobantes ---
    op.create_table(
        'invoice_series',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_type', sa.String(length=20), nullable=False),
        sa.Column('serie', sa.String(length=4), nullable=False),
        sa.Column('next_number', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_series')),
        sa.UniqueConstraint('tenant_id', 'document_type', 'serie', name=op.f('uq_invoice_series_tenant_id')),
    )
    op.create_index(op.f('ix_invoice_series_tenant_id'), 'invoice_series', ['tenant_id'], unique=False)

    # --- Comprobantes emitidos ---
    op.create_table(
        'invoices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('document_type', sa.String(length=20), nullable=False),
        sa.Column('serie', sa.String(length=4), nullable=False),
        sa.Column('numero', sa.Integer(), nullable=False),
        sa.Column('fecha_emision', sa.Date(), nullable=False),
        sa.Column('hora_emision', sa.String(length=8), nullable=True),
        sa.Column('fecha_vencimiento', sa.Date(), nullable=True),
        sa.Column('moneda', sa.String(length=3), nullable=False),
        sa.Column('tipo_operacion', sa.String(length=4), nullable=False),
        sa.Column('observacion', sa.Text(), nullable=True),
        sa.Column('cliente_tipo_doc', sa.String(length=4), nullable=False),
        sa.Column('cliente_numero_doc', sa.String(length=20), nullable=True),
        sa.Column('cliente_denominacion', sa.String(length=200), nullable=False),
        sa.Column('cliente_direccion', sa.String(length=300), nullable=True),
        sa.Column('total_gravada', sa.Float(), nullable=True),
        sa.Column('total_igv', sa.Float(), nullable=True),
        sa.Column('total_exonerada', sa.Float(), nullable=True),
        sa.Column('total_gratuita', sa.Float(), nullable=True),
        sa.Column('total', sa.Float(), nullable=False),
        sa.Column('nota_codigo_tipo', sa.String(length=2), nullable=True),
        sa.Column('nota_motivo', sa.String(length=200), nullable=True),
        sa.Column('documento_afectado_id', sa.Integer(), nullable=True),
        sa.Column('sunat_status', sa.String(length=20), nullable=False),
        sa.Column('sunat_hash', sa.String(length=100), nullable=True),
        sa.Column('sunat_message', sa.Text(), nullable=True),
        sa.Column('sunat_xml_url', sa.String(length=500), nullable=True),
        sa.Column('sunat_cdr_url', sa.String(length=500), nullable=True),
        sa.Column('sunat_pdf_ticket_url', sa.String(length=500), nullable=True),
        sa.Column('sunat_pdf_a4_url', sa.String(length=500), nullable=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_invoices_order_id_orders')),
        sa.ForeignKeyConstraint(
            ['documento_afectado_id'], ['invoices.id'], name=op.f('fk_invoices_documento_afectado_id_invoices')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invoices')),
        sa.UniqueConstraint(
            'tenant_id', 'document_type', 'serie', 'numero', name=op.f('uq_invoices_tenant_id')
        ),
    )
    op.create_index(op.f('ix_invoices_tenant_id'), 'invoices', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_invoices_order_id'), 'invoices', ['order_id'], unique=False)

    # --- Lineas de detalle de cada comprobante ---
    op.create_table(
        'invoice_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('unidad_medida', sa.String(length=5), nullable=False),
        sa.Column('codigo_interno', sa.String(length=30), nullable=True),
        sa.Column('descripcion', sa.String(length=300), nullable=False),
        sa.Column('cantidad', sa.Float(), nullable=False),
        sa.Column('valor_unitario', sa.Float(), nullable=False),
        sa.Column('precio_unitario', sa.Float(), nullable=True),
        sa.Column('porcentaje_igv', sa.Float(), nullable=False),
        sa.Column('codigo_tipo_afectacion_igv', sa.String(length=2), nullable=False),
        sa.Column('nombre_tributo', sa.String(length=10), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_invoice_items_invoice_id_invoices')),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_invoice_items_product_id_products')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_items')),
    )
    op.create_index(op.f('ix_invoice_items_tenant_id'), 'invoice_items', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_invoice_items_invoice_id'), 'invoice_items', ['invoice_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_invoice_items_invoice_id'), table_name='invoice_items')
    op.drop_index(op.f('ix_invoice_items_tenant_id'), table_name='invoice_items')
    op.drop_table('invoice_items')

    op.drop_index(op.f('ix_invoices_order_id'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_tenant_id'), table_name='invoices')
    op.drop_table('invoices')

    op.drop_index(op.f('ix_invoice_series_tenant_id'), table_name='invoice_series')
    op.drop_table('invoice_series')

    op.drop_column('products', 'igv_tribute_name')
    op.drop_column('products', 'igv_percentage')
    op.drop_column('products', 'igv_affectation_code')
    op.drop_column('products', 'unidad_medida')

    op.drop_column('customers', 'legal_name')
    op.drop_column('customers', 'doc_number')
    op.drop_column('customers', 'doc_type')

    op.drop_column('tenants', 'apisunat_environment')
    op.drop_column('tenants', 'apisunat_token')
    op.drop_column('tenants', 'fiscal_address')
    op.drop_column('tenants', 'legal_name')
    op.drop_column('tenants', 'ruc')
