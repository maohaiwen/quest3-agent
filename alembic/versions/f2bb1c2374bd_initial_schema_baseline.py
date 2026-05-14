"""initial_schema_baseline

Revision ID: f2bb1c2374bd
Revises: 
Create Date: 2026-05-14 01:33:25.007576

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2bb1c2374bd'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Baseline migration — marks the current schema as already applied.

    The actual tables are created by app.database.connection.initialize_schema()
    at application startup. This migration exists so that future schema changes
    can be tracked incrementally via Alembic.
    """
    pass


def downgrade() -> None:
    """No-op baseline — cannot downgrade below initial state."""
    pass
