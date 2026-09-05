"""estado de whatsapp en pedidos

Agrega whatsapp_status/whatsapp_sent_at a orders para que el panel de
Llamadas pueda mostrar de verdad si el aviso de confirmacion llego, en vez
de asumir que "se disparo" significa "llego". Ver
app/agents/runtime.py (_issue_invoice_and_notify / _notify_only).

Revision ID: dff6a10e7fd4
Revises: eb978181e03e
Create Date: 2026-09-05 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'dff6a10e7fd4'
down_revision: str | Sequence[str] | None = 'eb978181e03e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('whatsapp_status', sa.String(length=30), nullable=True))
    op.add_column('orders', sa.Column('whatsapp_sent_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'whatsapp_sent_at')
    op.drop_column('orders', 'whatsapp_status')
