"""track source version on knowledge chunks

Revision ID: 0002_chunk_source_version
Revises: 0001_initial_schema
Create Date: 2026-11-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_chunk_source_version"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record which source revision each chunk was built from.

    Retrieval joins the source and only serves chunks whose stored revision
    matches the current ``updated_at``. If re-indexing fails after a source
    edit, the old chunks remain in the table but are excluded, so the source
    never appears fully indexed against the new content.
    """
    op.add_column(
        "knowledge_chunks",
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove the source revision marker."""
    op.drop_column("knowledge_chunks", "source_updated_at")
