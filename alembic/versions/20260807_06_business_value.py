"""Business value: contracts, budgets, accounts and currency.

Revision ID: 20260807_06
Revises: 20260807_05
"""
from alembic import op
import sqlalchemy as sa

from database.models import Base

revision = "20260807_06"
down_revision = "20260807_05"
branch_labels = None
depends_on = None

TABLES = (
    "supplier_contracts", "supplier_contract_prices", "tour_budgets", "tour_budget_lines",
    "account_reconciliation_runs", "account_reconciliation_lines", "exchange_rates", "currency_settlements",
)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for name in TABLES:
        if name not in existing:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade():
    return None
