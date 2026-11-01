"""agent reviews: advisory multi-agent review next to the rule score

Revision ID: f1a7c3e9b2d6
Revises: e9a1b2c3d4f5
Create Date: 2026-11-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a7c3e9b2d6"
down_revision: Union[str, Sequence[str], None] = "e9a1b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_score", sa.Integer(), nullable=False),
        sa.Column("ai_score", sa.Integer(), nullable=False),
        sa.Column("final_score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("needs_choice", sa.Boolean(), nullable=False),
        sa.Column("chosen", sa.String(8)),
        sa.Column("chosen_by_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("chosen_reason", sa.Text()),
        sa.Column("chosen_at", sa.DateTime(timezone=True)),
        sa.Column("verdict", sa.String(24), nullable=False),
        sa.Column("stages_added", sa.JSON(), nullable=False),
        sa.Column("agents", sa.JSON(), nullable=False),
        sa.Column("aggregator", sa.JSON(), nullable=False),
        sa.Column("engine", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ai_score >= 0 AND ai_score <= 100", name="ck_agent_review_ai_score"),
        sa.CheckConstraint("final_score >= 0 AND final_score <= 100", name="ck_agent_review_final_score"),
    )
    op.create_index("ix_agent_reviews_request_id", "agent_reviews", ["request_id"], unique=True)
    op.create_index("ix_agent_reviews_status", "agent_reviews", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_reviews_status", table_name="agent_reviews")
    op.drop_index("ix_agent_reviews_request_id", table_name="agent_reviews")
    op.drop_table("agent_reviews")
