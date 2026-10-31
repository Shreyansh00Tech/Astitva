"""priority fields, routing reasons, alert resolution

Revision ID: b7e2a1c9d4f0
Revises: ccd77e69f635
Create Date: 2026-10-31 12:00:00

Additive only: new nullable columns (business_impact has a server default). No data is removed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7e2a1c9d4f0"
down_revision: Union[str, Sequence[str], None] = "ccd77e69f635"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_requests", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("access_requests", sa.Column("business_impact", sa.String(10), nullable=False, server_default="MEDIUM"))
    op.add_column("access_requests", sa.Column("routing_reasons", sa.JSON(), nullable=True))
    op.create_index("ix_access_requests_deadline_at", "access_requests", ["deadline_at"])
    op.add_column("security_alerts", sa.Column("resolution", sa.String(16), nullable=True))
    op.create_index("ix_security_alerts_resolution", "security_alerts", ["resolution"])


def downgrade() -> None:
    op.drop_index("ix_security_alerts_resolution", "security_alerts")
    op.drop_column("security_alerts", "resolution")
    op.drop_index("ix_access_requests_deadline_at", "access_requests")
    op.drop_column("access_requests", "routing_reasons")
    op.drop_column("access_requests", "business_impact")
    op.drop_column("access_requests", "deadline_at")
