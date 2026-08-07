"""Phase 4 communication automations.

Revision ID: 20260807_05
Revises: 20260807_04
"""
from alembic import op
import sqlalchemy as sa
from database.models import Base

revision = "20260807_05"
down_revision = "20260807_04"
branch_labels = None
depends_on = None

TABLES = (
    "email_accounts", "email_ingestion_batches", "email_messages", "email_attachments", "email_processing_events",
    "whatsapp_accounts", "whatsapp_conversations", "whatsapp_messages", "whatsapp_media", "reservation_candidates", "reservation_candidate_fields", "reservation_candidate_events",
    "notification_templates", "notifications", "notification_deliveries", "notification_preferences", "notification_events",
    "scheduled_jobs", "job_runs", "job_locks",
)


def upgrade():
    bind = op.get_bind(); existing = set(sa.inspect(bind).get_table_names())
    for name in TABLES:
        if name not in existing: Base.metadata.tables[name].create(bind=bind, checkfirst=True)
    columns = {item["name"] for item in sa.inspect(bind).get_columns("approval_requests")}
    additions = {
        "source": sa.Column("source", sa.String(100)), "severity": sa.Column("severity", sa.String(50), nullable=False, server_default="Bilgi"),
        "due_date": sa.Column("due_date", sa.DateTime()), "priority_score": sa.Column("priority_score", sa.Numeric(8, 2), nullable=False, server_default="0"),
        "ai_confidence": sa.Column("ai_confidence", sa.Numeric(5, 2)), "deterministic_checks": sa.Column("deterministic_checks", sa.JSON()), "affected_records": sa.Column("affected_records", sa.JSON()),
    }
    for name, column in additions.items():
        if name not in columns: op.add_column("approval_requests", column)


def downgrade():
    return None
