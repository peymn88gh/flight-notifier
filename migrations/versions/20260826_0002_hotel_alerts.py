"""Add alert kind discriminator for hotel monitoring."""

import sqlalchemy as sa
from alembic import op

revision = "20260826_0002"
down_revision = "20260811_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("kind", sa.String(16), nullable=False, server_default="flight"),
    )
    op.create_index("ix_alerts_kind", "alerts", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_alerts_kind", table_name="alerts")
    op.drop_column("alerts", "kind")
