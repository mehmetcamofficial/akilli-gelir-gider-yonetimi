"""Add persistent Google Drive metadata to documents.

Revision ID: 20260807_02
Revises: 20260807_01
"""
from alembic import op
import sqlalchemy as sa


revision = "20260807_02"
down_revision = "20260807_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "storage_provider" not in columns:
        op.add_column("documents", sa.Column("storage_provider", sa.String(50), nullable=False, server_default="local"))
    if "drive_file_id" not in columns:
        op.add_column("documents", sa.Column("drive_file_id", sa.String(255), nullable=True))
        op.create_index("ix_documents_drive_file_id", "documents", ["drive_file_id"], unique=True)
    if "drive_web_view_link" not in columns:
        op.add_column("documents", sa.Column("drive_web_view_link", sa.String(1024), nullable=True))


def downgrade():
    # Persistent document metadata is intentionally retained in production.
    pass
