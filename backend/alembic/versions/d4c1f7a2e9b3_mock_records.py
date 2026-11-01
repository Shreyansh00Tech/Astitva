"""mock records for the simulated model / dataset / database workspaces

Revision ID: d4c1f7a2e9b3
Revises: b7e2a1c9d4f0
Create Date: 2026-10-31 23:00:00

Additive only: one new table of synthetic rows. No existing data is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4c1f7a2e9b3"
down_revision: Union[str, Sequence[str], None] = "b7e2a1c9d4f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mock_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource_id", sa.String(36), sa.ForeignKey("resources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_name", sa.String(48), nullable=False),
        sa.Column("record_key", sa.String(48), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("resource_id", "table_name", "record_key", name="uq_mock_record_key"),
    )
    op.create_index("ix_mock_records_resource_id", "mock_records", ["resource_id"])
    op.create_index("ix_mock_records_res_table", "mock_records", ["resource_id", "table_name"])


def downgrade() -> None:
    op.drop_index("ix_mock_records_res_table", "mock_records")
    op.drop_index("ix_mock_records_resource_id", "mock_records")
    op.drop_table("mock_records")
