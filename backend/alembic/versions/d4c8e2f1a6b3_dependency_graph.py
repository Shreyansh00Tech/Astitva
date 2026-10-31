"""access dependency graph: service links, agent permission revocation

Revision ID: d4c8e2f1a6b3
Revises: b7e2a1c9d4f0
Create Date: 2026-10-31 22:00:00

Additive only: one new table and two nullable columns. If the resources already exist (a database seeded before
this migration), the default simulated service links are inserted so the graph works without a reset.
"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4c8e2f1a6b3"
down_revision: Union[str, Sequence[str], None] = "b7e2a1c9d4f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_permissions", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_permissions", sa.Column("revoked_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True))
    deps = op.create_table(
        "resource_dependencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource_id", sa.String(36), sa.ForeignKey("resources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dependent_resource_id", sa.String(36), sa.ForeignKey("resources.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("endpoint", sa.String(160), nullable=True),
        sa.Column("criticality", sa.String(10), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("suspend_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resource_dependencies_resource_id", "resource_dependencies", ["resource_id"])
    op.create_index("ix_resource_dependencies_dependent_resource_id", "resource_dependencies", ["dependent_resource_id"])

    from app.core.dependency_catalog import DEFAULT_DEPENDENCIES

    conn = op.get_bind()
    ids = dict(conn.execute(sa.text("SELECT code, id FROM resources")).all())
    now = datetime.now(timezone.utc)
    rows = [
        {"id": str(uuid.uuid4()), "resource_id": ids[up], "dependent_resource_id": ids.get(down) if down else None,
         "name": name, "kind": kind, "endpoint": endpoint, "criticality": crit, "description": desc,
         "created_at": now, "updated_at": now}
        for up, down, name, kind, endpoint, crit, desc in DEFAULT_DEPENDENCIES
        if up in ids and (down is None or down in ids)
    ]
    if rows:
        op.bulk_insert(deps, rows)


def downgrade() -> None:
    op.drop_index("ix_resource_dependencies_dependent_resource_id", "resource_dependencies")
    op.drop_index("ix_resource_dependencies_resource_id", "resource_dependencies")
    op.drop_table("resource_dependencies")
    op.drop_column("agent_permissions", "revoked_by_id")
    op.drop_column("agent_permissions", "revoked_at")
