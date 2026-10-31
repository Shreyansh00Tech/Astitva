"""project timeline dates, team name, and project link on requests and grants

Revision ID: c3f5d8e1a2b4
Revises: b7e2a1c9d4f0
Create Date: 2026-10-31 23:00:00

Additive only: new nullable columns. No data is removed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3f5d8e1a2b4"
down_revision: Union[str, Sequence[str], None] = "b7e2a1c9d4f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("team_name", sa.String(120), nullable=True))
    op.add_column("projects", sa.Column("start_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("submission_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("end_date", sa.DateTime(timezone=True), nullable=True))
    for table in ("access_requests", "access_grants"):
        op.add_column(table, sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=True))
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])


def downgrade() -> None:
    for table in ("access_grants", "access_requests"):
        op.drop_index(f"ix_{table}_project_id", table)
        op.drop_column(table, "project_id")
    for col in ("end_date", "submission_date", "start_date", "team_name"):
        op.drop_column("projects", col)
