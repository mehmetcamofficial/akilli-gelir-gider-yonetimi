"""Complete contract and price management.

Revision ID: 20260807_07
Revises: 20260807_06
"""
from alembic import op
import sqlalchemy as sa

from database.models import Base

revision = "20260807_07"
down_revision = "20260807_06"
branch_labels = None
depends_on = None

TABLES = (
    "contract_versions", "contract_price_rules", "restaurant_price_rules",
    "hotel_price_rules", "transfer_price_rules", "guide_price_rules",
    "contract_documents", "contract_price_history",
)

ADDITIONS = {
    "contract_type": sa.Column("contract_type", sa.String(50)),
    "title": sa.Column("title", sa.String(255)),
    "description": sa.Column("description", sa.Text()),
    "valid_until": sa.Column("valid_until", sa.DateTime()),
    "tax_included": sa.Column("tax_included", sa.Boolean(), nullable=False, server_default=sa.false()),
    "tax_rate": sa.Column("tax_rate", sa.Numeric(8, 4), nullable=False, server_default="0"),
    "payment_method": sa.Column("payment_method", sa.String(100)),
    "cancellation_policy": sa.Column("cancellation_policy", sa.Text()),
    "active": sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    "status": sa.Column("status", sa.String(50), nullable=False, server_default="Taslak"),
    "document_id": sa.Column("document_id", sa.Integer()),
    "updated_at": sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
}


def upgrade():
    bind = op.get_bind(); inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("supplier_contracts")}
    for name, column in ADDITIONS.items():
        if name not in columns:
            op.add_column("supplier_contracts", column)
    existing = set(sa.inspect(bind).get_table_names())
    for name in TABLES:
        if name not in existing:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade():
    return None
