"""Phase 2 accounting automation tables and workflow fields.

Revision ID: 20260807_03
Revises: 20260807_02
"""
from alembic import op
import sqlalchemy as sa


revision = "20260807_03"
down_revision = "20260807_02"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table, column):
    if column.name not in _columns(table):
        if op.get_bind().dialect.name == "sqlite" and column.foreign_keys:
            column = sa.Column(column.name, column.type, nullable=column.nullable)
        op.add_column(table, column)


def _index(table, name, columns, unique=False):
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    tables = _tables()
    if "import_batch_rows" not in tables:
        op.create_table("import_batch_rows", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=False), sa.Column("row_number", sa.Integer(), nullable=False), sa.Column("raw_values", sa.JSON(), nullable=False), sa.Column("normalized_values", sa.JSON()), sa.Column("validation_messages", sa.JSON()), sa.Column("status", sa.String(50), nullable=False), sa.Column("target_entity_type", sa.String(100)), sa.Column("target_entity_id", sa.Integer()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("batch_id", "row_number", name="uq_import_batch_rows_batch_row"))
        op.create_index("ix_import_batch_rows_batch_id", "import_batch_rows", ["batch_id"])
        op.create_index("ix_import_batch_rows_status", "import_batch_rows", ["status"])
    if "import_mapping_templates" not in tables:
        op.create_table("import_mapping_templates", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("source_type", sa.String(100), nullable=False), sa.Column("owner_key", sa.String(255)), sa.Column("dataset_type", sa.String(100), nullable=False), sa.Column("mapping_configuration", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
        op.create_index("ix_import_mapping_templates_source_type", "import_mapping_templates", ["source_type"])
        op.create_index("ix_import_mapping_templates_owner_key", "import_mapping_templates", ["owner_key"])
    if "restaurant_reconciliations" not in tables:
        op.create_table("restaurant_reconciliations", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("reconciliation_id", sa.Integer(), sa.ForeignKey("document_reconciliations.id")), sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id")), sa.Column("voucher_number", sa.String(200)), sa.Column("invoice_number", sa.String(200)), sa.Column("calculated_values", sa.JSON(), nullable=False), sa.Column("differences", sa.JSON(), nullable=False), sa.Column("expected_total", sa.Numeric(18, 2)), sa.Column("invoice_total", sa.Numeric(18, 2)), sa.Column("potential_overpayment", sa.Numeric(18, 2), nullable=False, server_default="0"), sa.Column("status", sa.String(50), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
        for name in ("reconciliation_id", "supplier_id", "voucher_number", "invoice_number", "status"): op.create_index(f"ix_restaurant_reconciliations_{name}", "restaurant_reconciliations", [name])
    if "hotel_reconciliations" not in tables:
        op.create_table("hotel_reconciliations", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("reconciliation_id", sa.Integer(), sa.ForeignKey("document_reconciliations.id")), sa.Column("hotel_id", sa.Integer(), sa.ForeignKey("hotels.id")), sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id")), sa.Column("invoice_number", sa.String(200)), sa.Column("calculated_values", sa.JSON(), nullable=False), sa.Column("differences", sa.JSON(), nullable=False), sa.Column("expected_total", sa.Numeric(18, 2)), sa.Column("invoice_total", sa.Numeric(18, 2)), sa.Column("status", sa.String(50), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
        for name in ("reconciliation_id", "hotel_id", "booking_id", "invoice_number", "status"): op.create_index(f"ix_hotel_reconciliations_{name}", "hotel_reconciliations", [name])
    if "bank_import_batches" not in tables:
        op.create_table("bank_import_batches", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id")), sa.Column("filename", sa.String(512), nullable=False), sa.Column("file_hash", sa.String(128), nullable=False), sa.Column("mapping_configuration", sa.JSON()), sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"), sa.Column("imported_rows", sa.Integer(), nullable=False, server_default="0"), sa.Column("duplicate_rows", sa.Integer(), nullable=False, server_default="0"), sa.Column("status", sa.String(50), nullable=False, server_default="Taslak"), sa.Column("started_at", sa.DateTime(), nullable=False), sa.Column("completed_at", sa.DateTime()))
        for name in ("bank_account_id", "file_hash", "status"): op.create_index(f"ix_bank_import_batches_{name}", "bank_import_batches", [name])
    if "bank_reconciliation_matches" not in tables:
        op.create_table("bank_reconciliation_matches", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("bank_transaction_id", sa.Integer(), sa.ForeignKey("bank_transactions.id"), nullable=False), sa.Column("entity_type", sa.String(100), nullable=False), sa.Column("entity_id", sa.Integer(), nullable=False), sa.Column("allocated_amount", sa.Numeric(18, 2), nullable=False), sa.Column("confidence", sa.Numeric(5, 2)), sa.Column("match_reason", sa.Text()), sa.Column("status", sa.String(50), nullable=False, server_default="Onay Bekliyor"), sa.Column("approved_at", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False))
        op.create_index("ix_bank_reconciliation_matches_bank_transaction_id", "bank_reconciliation_matches", ["bank_transaction_id"])
        op.create_index("ix_bank_reconciliation_matches_status", "bank_reconciliation_matches", ["status"])
    if "approval_requests" not in tables:
        op.create_table("approval_requests", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_type", sa.String(100), nullable=False), sa.Column("source_entity_type", sa.String(100)), sa.Column("source_entity_id", sa.Integer()), sa.Column("proposed_action", sa.String(255), nullable=False), sa.Column("before_values", sa.JSON()), sa.Column("after_values", sa.JSON()), sa.Column("detected_differences", sa.JSON()), sa.Column("financial_effect", sa.Numeric(18, 2)), sa.Column("related_documents", sa.JSON()), sa.Column("status", sa.String(50), nullable=False, server_default="Taslak"), sa.Column("approver_name", sa.String(255)), sa.Column("approval_note", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("decided_at", sa.DateTime()))
        op.create_index("ix_approval_requests_request_type", "approval_requests", ["request_type"])
        op.create_index("ix_approval_requests_status", "approval_requests", ["status"])

    for name, column in {
        "reconciliation_type": sa.Column("reconciliation_type", sa.String(50), nullable=False, server_default="document"),
        "approval_status": sa.Column("approval_status", sa.String(50), nullable=False, server_default="Taslak"),
    }.items(): _add("document_reconciliations", column)
    for name, column in {
        "batch_id": sa.Column("batch_id", sa.Integer()), "reconciliation_id": sa.Column("reconciliation_id", sa.Integer()), "action": sa.Column("action", sa.String(100)), "old_values": sa.Column("old_values", sa.JSON()), "new_values": sa.Column("new_values", sa.JSON()), "reason": sa.Column("reason", sa.Text()), "actor_name": sa.Column("actor_name", sa.String(255)), "source": sa.Column("source", sa.String(100)), "ip_address": sa.Column("ip_address", sa.String(64)), "status": sa.Column("status", sa.String(50)),
    }.items(): _add("audit_logs", column)
    for name, column in {
        "source_type": sa.Column("source_type", sa.String(100), nullable=False, server_default="local"), "worksheet": sa.Column("worksheet", sa.String(255)), "mapping_configuration": sa.Column("mapping_configuration", sa.JSON()), "valid_rows": sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"), "invalid_rows": sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"), "started_at": sa.Column("started_at", sa.DateTime()), "completed_at": sa.Column("completed_at", sa.DateTime()), "status": sa.Column("status", sa.String(50), nullable=False, server_default="Taslak"),
    }.items(): _add("import_batches", column)
    for name, column in {
        "bank_account_id": sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id")), "bank_import_batch_id": sa.Column("bank_import_batch_id", sa.Integer(), sa.ForeignKey("bank_import_batches.id")), "value_date": sa.Column("value_date", sa.DateTime()), "counterparty": sa.Column("counterparty", sa.String(255)), "counterparty_iban": sa.Column("counterparty_iban", sa.String(255)), "debit_amount": sa.Column("debit_amount", sa.Numeric(18, 2), server_default="0"), "credit_amount": sa.Column("credit_amount", sa.Numeric(18, 2), server_default="0"), "balance": sa.Column("balance", sa.Numeric(18, 2)), "raw_row": sa.Column("raw_row", sa.JSON()), "transaction_hash": sa.Column("transaction_hash", sa.String(128)), "status": sa.Column("status", sa.String(50), nullable=False, server_default="Yeni"),
    }.items(): _add("bank_transactions", column)
    _index("document_reconciliations", "ix_document_reconciliations_approval_status", ["approval_status"])
    _index("document_reconciliations", "ix_document_reconciliations_reconciliation_type", ["reconciliation_type"])
    _index("import_batches", "ix_import_batches_status", ["status"])
    _index("bank_transactions", "ix_bank_transactions_transaction_hash", ["transaction_hash"], unique=True)
    _index("bank_transactions", "ix_bank_transactions_status", ["status"])
    _index("bank_transactions", "ix_bank_transactions_bank_account_id", ["bank_account_id"])
    _index("bank_transactions", "ix_bank_transactions_bank_import_batch_id", ["bank_import_batch_id"])


def downgrade():
    # Production data is intentionally preserved; this migration is forward-only.
    return None
