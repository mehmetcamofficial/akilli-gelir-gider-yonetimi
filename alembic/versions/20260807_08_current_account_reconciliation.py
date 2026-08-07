"""Automatic current account reconciliation.

Revision ID: 20260807_08
Revises: 20260807_07
"""
from alembic import op
import sqlalchemy as sa
from database.models import Base

revision = "20260807_08"
down_revision = "20260807_07"
branch_labels = None
depends_on = None

TABLES = (
    "current_accounts", "current_account_movements", "open_items", "open_item_matches",
    "account_reconciliations", "account_reconciliation_differences",
    "account_reconciliation_responses", "account_risk_scores", "exchange_difference_entries",
)


def upgrade():
    bind = op.get_bind(); existing = set(sa.inspect(bind).get_table_names())
    for name in TABLES:
        if name not in existing:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade():
    return None
