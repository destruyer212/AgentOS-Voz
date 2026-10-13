"""payment_reference en pedidos

Agrega orders.payment_reference -- codigo de aprobacion "ficticio" de
Yape (ver agents/runtime.py, _DETAIL_PROMPTS["yape_code"]). No se
verifica contra ninguna API real de Yape (no la tenemos integrada); solo
se valida el formato (3 digitos exactos) por voz y se guarda tal cual
para que el negocio lo cruce a mano contra su propio Yape. Solo se llena
cuando payment_method == "yape".

Revision ID: a1c5f3d8e2b7
Revises: dff6a10e7fd4
Create Date: 2026-10-12 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c5f3d8e2b7'
down_revision: str | Sequence[str] | None = 'dff6a10e7fd4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('payment_reference', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'payment_reference')
