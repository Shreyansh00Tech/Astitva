"""personal planner: tasks and events employees add to their own calendar

Revision ID: f2b6c9d1e3a7
Revises: f1a7c3e9b2d6
Create Date: 2026-11-01

Additive only: one new table. No data is removed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2b6c9d1e3a7"
down_revision: Union[str, Sequence[str], None] = "f1a7c3e9b2d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planner_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("category", sa.String(16), nullable=False, server_default="WORK"),
        sa.Column("priority", sa.String(8), nullable=False, server_default="MEDIUM"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_planner_items_user_id", "planner_items", ["user_id"])
    op.create_index("ix_planner_items_start_at", "planner_items", ["start_at"])


def downgrade() -> None:
    op.drop_index("ix_planner_items_start_at", "planner_items")
    op.drop_index("ix_planner_items_user_id", "planner_items")
    op.drop_table("planner_items")
