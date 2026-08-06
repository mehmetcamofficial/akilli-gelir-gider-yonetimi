"""Create the complete tourism application schema safely.

Revision ID: 20260807_01
Revises:
"""
from database.models import Base
from alembic import op


revision = "20260807_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    # Production data is intentionally never dropped automatically.
    pass
