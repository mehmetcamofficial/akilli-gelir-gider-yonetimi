"""Phase 3 centralized AI features.

Revision ID: 20260807_04
Revises: 20260807_03
"""
from alembic import op
import sqlalchemy as sa

from database.models import Base


revision = "20260807_04"
down_revision = "20260807_03"
branch_labels = None
depends_on = None


AI_TABLES = (
    "ai_requests", "ai_usage_logs", "ai_extractions", "ai_extraction_fields",
    "ai_field_corrections", "document_confidence_scores", "assistant_queries",
    "anomaly_explanations", "supplier_objection_drafts", "management_commentaries",
)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table_name in AI_TABLES:
        if table_name not in existing:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade():
    # AI history is retained intentionally in production.
    return None
