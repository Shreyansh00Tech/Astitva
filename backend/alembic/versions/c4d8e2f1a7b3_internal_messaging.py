"""internal messaging between employees and managers

Revision ID: c4d8e2f1a7b3
Revises: b7e2a1c9d4f0
Create Date: 2026-10-31 23:00:00

Additive only: three new tables. No existing data is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4d8e2f1a7b3"
down_revision: Union[str, Sequence[str], None] = "b7e2a1c9d4f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pair_key", sa.String(80), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])
    op.create_table(
        "conversation_participants",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversation_participants_user_id", "conversation_participants", ["user_id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_conv_created", "chat_messages", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conv_created", "chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversation_participants_user_id", "conversation_participants")
    op.drop_table("conversation_participants")
    op.drop_index("ix_conversations_last_message_at", "conversations")
    op.drop_table("conversations")
