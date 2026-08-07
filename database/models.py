from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean, ForeignKey, Text, JSON, Index
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
from decimal import Decimal

Base = declarative_base()


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    children = relationship("Category")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    transaction_type = Column(String(20), nullable=False)  # income or expense
    invoice_type = Column(String(20), nullable=True)  # sale or purchase (optional)
    transaction_date = Column(DateTime, default=datetime.utcnow)
    document_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    invoice_number = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    party_name = Column(String(255), nullable=True)
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18, 6), default=Decimal("1.0"))
    subtotal = Column(Numeric(18, 2), default=Decimal("0.00"))
    tax_total = Column(Numeric(18, 2), default=Decimal("0.00"))
    discount_total = Column(Numeric(18, 2), default=Decimal("0.00"))
    grand_total = Column(Numeric(18, 2), default=Decimal("0.00"))
    paid_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    remaining_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    payment_status = Column(String(50), default="Ödenmedi")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    documents = relationship("Document", back_populates="transaction")
    items = relationship("InvoiceItem", back_populates="invoice")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    original_filename = Column(String(512))
    stored_filename = Column(String(512))
    file_path = Column(String(1024))
    file_type = Column(String(50))
    file_hash = Column(String(128), index=True)
    file_size = Column(Integer)
    storage_provider = Column(String(50), default="local", nullable=False)
    drive_file_id = Column(String(255), nullable=True, unique=True, index=True)
    drive_web_view_link = Column(String(1024), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    transaction = relationship("Transaction", back_populates="documents")


class DocumentReconciliation(Base):
    __tablename__ = "document_reconciliations"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    document_hash = Column(String(128), nullable=False, index=True)
    extracted_json = Column(Text, nullable=False)
    matched_entity_type = Column(String(100), nullable=True)
    matched_entity_id = Column(Integer, nullable=True)
    status = Column(String(100), nullable=False)
    severity = Column(String(50), nullable=False)
    differences_json = Column(Text, nullable=False)
    expected_total = Column(Numeric(18, 2), nullable=True)
    document_total = Column(Numeric(18, 2), nullable=True)
    difference_amount = Column(Numeric(18, 2), nullable=True)
    difference_percentage = Column(Numeric(18, 4), nullable=True)
    recommended_action = Column(Text, nullable=True)
    user_action = Column(String(100), nullable=True)
    user_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reconciliation_type = Column(String(50), default="document", nullable=False, index=True)
    approval_status = Column(String(50), default="Taslak", nullable=False, index=True)


class ReconciliationDocument(Base):
    __tablename__ = "reconciliation_documents"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=False, index=True)
    side = Column(String(20), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    source_type = Column(String(100), nullable=False)
    source_entity_type = Column(String(100), nullable=True)
    source_entity_id = Column(Integer, nullable=True)
    filename = Column(String(512), nullable=True)
    file_hash = Column(String(128), nullable=True, index=True)
    content_base64 = Column(Text, nullable=True)
    extracted_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ReconciliationField(Base):
    __tablename__ = "reconciliation_fields"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    incoming_value = Column(Text, nullable=True)
    agency_value = Column(Text, nullable=True)
    status = Column(String(100), nullable=False)
    explanation = Column(Text, nullable=True)


class ReconciliationDifference(Base):
    __tablename__ = "reconciliation_differences"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    incoming_value = Column(Text, nullable=True)
    agency_value = Column(Text, nullable=True)
    difference_value = Column(Text, nullable=True)
    severity = Column(String(50), nullable=False)
    explanation = Column(Text, nullable=True)


class ReconciliationApproval(Base):
    __tablename__ = "reconciliation_approvals"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=False, index=True)
    action = Column(String(100), nullable=False)
    destination = Column(String(100), nullable=True)
    approved_by = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(Integer, nullable=True)
    details_json = Column(Text, nullable=True)
    batch_id = Column(Integer, nullable=True, index=True)
    reconciliation_id = Column(Integer, nullable=True, index=True)
    action = Column(String(100), nullable=True, index=True)
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    actor_name = Column(String(255), nullable=True, index=True)
    source = Column(String(100), nullable=True)
    ip_address = Column(String(64), nullable=True)
    status = Column(String(50), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id = Column(Integer, primary_key=True)
    filename = Column(String(512), nullable=False)
    file_hash = Column(String(128), nullable=False, index=True)
    dataset_type = Column(String(100), nullable=False)
    total_rows = Column(Integer, default=0)
    imported_rows = Column(Integer, default=0)
    skipped_rows = Column(Integer, default=0)
    error_rows = Column(Integer, default=0)
    duplicate_rows = Column(Integer, default=0)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    source_type = Column(String(100), default="local", nullable=False)
    worksheet = Column(String(255), nullable=True)
    mapping_configuration = Column(JSON, nullable=True)
    valid_rows = Column(Integer, default=0)
    invalid_rows = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="Taslak", nullable=False, index=True)


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    id = Column(Integer, primary_key=True)
    transaction_date = Column(DateTime, nullable=True)
    description = Column(Text, nullable=True)
    reference_number = Column(String(255), nullable=True)
    amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    currency = Column(String(10), default="TRY")
    transaction_type = Column(String(20), nullable=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True, index=True)
    bank_import_batch_id = Column(Integer, ForeignKey("bank_import_batches.id"), nullable=True, index=True)
    value_date = Column(DateTime, nullable=True)
    counterparty = Column(String(255), nullable=True)
    counterparty_iban = Column(String(255), nullable=True)
    debit_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    credit_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    balance = Column(Numeric(18, 2), nullable=True)
    raw_row = Column(JSON, nullable=True)
    transaction_hash = Column(String(128), nullable=True, unique=True, index=True)
    status = Column(String(50), default="Yeni", nullable=False, index=True)


class ImportBatchRow(Base):
    __tablename__ = "import_batch_rows"
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    raw_values = Column(JSON, nullable=False)
    normalized_values = Column(JSON, nullable=True)
    validation_messages = Column(JSON, nullable=True)
    status = Column(String(50), nullable=False, index=True)
    target_entity_type = Column(String(100), nullable=True)
    target_entity_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("ix_import_batch_rows_batch_row", "batch_id", "row_number", unique=True),)


class ImportMappingTemplate(Base):
    __tablename__ = "import_mapping_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    source_type = Column(String(100), nullable=False, index=True)
    owner_key = Column(String(255), nullable=True, index=True)
    dataset_type = Column(String(100), nullable=False)
    mapping_configuration = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RestaurantReconciliation(Base):
    __tablename__ = "restaurant_reconciliations"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    voucher_number = Column(String(200), nullable=True, index=True)
    invoice_number = Column(String(200), nullable=True, index=True)
    calculated_values = Column(JSON, nullable=False)
    differences = Column(JSON, nullable=False)
    expected_total = Column(Numeric(18, 2), nullable=True)
    invoice_total = Column(Numeric(18, 2), nullable=True)
    potential_overpayment = Column(Numeric(18, 2), default=Decimal("0.00"))
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class HotelReconciliation(Base):
    __tablename__ = "hotel_reconciliations"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=True, index=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True, index=True)
    invoice_number = Column(String(200), nullable=True, index=True)
    calculated_values = Column(JSON, nullable=False)
    differences = Column(JSON, nullable=False)
    expected_total = Column(Numeric(18, 2), nullable=True)
    invoice_total = Column(Numeric(18, 2), nullable=True)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BankImportBatch(Base):
    __tablename__ = "bank_import_batches"
    id = Column(Integer, primary_key=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True, index=True)
    filename = Column(String(512), nullable=False)
    file_hash = Column(String(128), nullable=False, index=True)
    mapping_configuration = Column(JSON, nullable=True)
    total_rows = Column(Integer, default=0)
    imported_rows = Column(Integer, default=0)
    duplicate_rows = Column(Integer, default=0)
    status = Column(String(50), default="Taslak", nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class BankReconciliationMatch(Base):
    __tablename__ = "bank_reconciliation_matches"
    id = Column(Integer, primary_key=True)
    bank_transaction_id = Column(Integer, ForeignKey("bank_transactions.id"), nullable=False, index=True)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(Integer, nullable=False)
    allocated_amount = Column(Numeric(18, 2), nullable=False)
    confidence = Column(Numeric(5, 2), nullable=True)
    match_reason = Column(Text, nullable=True)
    status = Column(String(50), default="Onay Bekliyor", nullable=False, index=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id = Column(Integer, primary_key=True)
    request_type = Column(String(100), nullable=False, index=True)
    source_entity_type = Column(String(100), nullable=True)
    source_entity_id = Column(Integer, nullable=True)
    proposed_action = Column(String(255), nullable=False)
    before_values = Column(JSON, nullable=True)
    after_values = Column(JSON, nullable=True)
    detected_differences = Column(JSON, nullable=True)
    financial_effect = Column(Numeric(18, 2), nullable=True)
    related_documents = Column(JSON, nullable=True)
    status = Column(String(50), default="Taslak", nullable=False, index=True)
    approver_name = Column(String(255), nullable=True)
    approval_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    decided_at = Column(DateTime, nullable=True)
    source = Column(String(100), nullable=True, index=True)
    severity = Column(String(50), default="Bilgi", nullable=False, index=True)
    due_date = Column(DateTime, nullable=True, index=True)
    priority_score = Column(Numeric(8, 2), default=Decimal("0"), nullable=False, index=True)
    ai_confidence = Column(Numeric(5, 2), nullable=True)
    deterministic_checks = Column(JSON, nullable=True)
    affected_records = Column(JSON, nullable=True)


class AIRequest(Base):
    __tablename__ = "ai_requests"
    id = Column(Integer, primary_key=True)
    request_id = Column(String(100), nullable=False, unique=True, index=True)
    request_type = Column(String(100), nullable=False, index=True)
    model = Column(String(200), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    related_entity_type = Column(String(100), nullable=True, index=True)
    related_entity_id = Column(Integer, nullable=True, index=True)
    masked_summary = Column(JSON, nullable=True)
    status = Column(String(50), nullable=False, index=True)
    error_code = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AIUsageLog(Base):
    __tablename__ = "ai_usage_logs"
    id = Column(Integer, primary_key=True)
    request_id = Column(String(100), nullable=False, index=True)
    request_type = Column(String(100), nullable=False, index=True)
    model = Column(String(200), nullable=False, index=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    estimated_cost = Column(Numeric(18, 6), default=Decimal("0"))
    duration_ms = Column(Integer, default=0)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AIExtraction(Base):
    __tablename__ = "ai_extractions"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    ai_request_id = Column(Integer, ForeignKey("ai_requests.id"), nullable=True, index=True)
    document_type = Column(String(100), nullable=True)
    original_values = Column(JSON, nullable=False)
    approved_values = Column(JSON, nullable=True)
    validation_results = Column(JSON, nullable=True)
    overall_confidence = Column(Numeric(5, 2), nullable=True, index=True)
    status = Column(String(50), default="Onay Bekliyor", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    approved_at = Column(DateTime, nullable=True)


class AIExtractionField(Base):
    __tablename__ = "ai_extraction_fields"
    id = Column(Integer, primary_key=True)
    extraction_id = Column(Integer, ForeignKey("ai_extractions.id"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    value = Column(JSON, nullable=True)
    confidence = Column(Numeric(5, 2), nullable=True)
    source_page = Column(Integer, nullable=True)
    source_text = Column(Text, nullable=True)
    bounding_box = Column(JSON, nullable=True)
    status = Column(String(50), nullable=False)


class AIFieldCorrection(Base):
    __tablename__ = "ai_field_corrections"
    id = Column(Integer, primary_key=True)
    extraction_field_id = Column(Integer, ForeignKey("ai_extraction_fields.id"), nullable=False, index=True)
    original_value = Column(JSON, nullable=True)
    corrected_value = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    actor_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class DocumentConfidenceScore(Base):
    __tablename__ = "document_confidence_scores"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    extraction_id = Column(Integer, ForeignKey("ai_extractions.id"), nullable=True, index=True)
    confidence_score = Column(Numeric(5, 2), nullable=False, index=True)
    score_class = Column(String(50), nullable=False)
    components = Column(JSON, nullable=False)
    reasons = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AssistantQuery(Base):
    __tablename__ = "assistant_queries"
    id = Column(Integer, primary_key=True)
    ai_request_id = Column(Integer, ForeignKey("ai_requests.id"), nullable=True, index=True)
    question_masked = Column(Text, nullable=False)
    intent = Column(String(100), nullable=False, index=True)
    analytics_function = Column(String(150), nullable=True)
    filters = Column(JSON, nullable=True)
    result_summary = Column(JSON, nullable=True)
    answer = Column(Text, nullable=True)
    history_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AnomalyExplanation(Base):
    __tablename__ = "anomaly_explanations"
    id = Column(Integer, primary_key=True)
    ai_request_id = Column(Integer, ForeignKey("ai_requests.id"), nullable=True, index=True)
    anomaly_type = Column(String(100), nullable=False, index=True)
    related_entity_type = Column(String(100), nullable=True, index=True)
    related_entity_id = Column(Integer, nullable=True, index=True)
    severity = Column(String(50), nullable=False)
    facts = Column(JSON, nullable=False)
    explanation = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class SupplierObjectionDraft(Base):
    __tablename__ = "supplier_objection_drafts"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=True, index=True)
    ai_request_id = Column(Integer, ForeignKey("ai_requests.id"), nullable=True, index=True)
    language = Column(String(10), nullable=False)
    tone = Column(String(30), nullable=False)
    verified_facts = Column(JSON, nullable=False)
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(50), default="Taslak", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ManagementCommentary(Base):
    __tablename__ = "management_commentaries"
    id = Column(Integer, primary_key=True)
    ai_request_id = Column(Integer, ForeignKey("ai_requests.id"), nullable=True, index=True)
    commentary_type = Column(String(100), nullable=False, index=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    facts = Column(JSON, nullable=False)
    commentary = Column(Text, nullable=False)
    detail_level = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class EmailAccount(Base):
    __tablename__ = "email_accounts"
    id = Column(Integer, primary_key=True); provider = Column(String(50), nullable=False); account_address = Column(String(255), nullable=False); mailbox_label = Column(String(255)); is_active = Column(Boolean, default=True, nullable=False); last_successful_sync = Column(DateTime); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class EmailIngestionBatch(Base):
    __tablename__ = "email_ingestion_batches"
    id = Column(Integer, primary_key=True); account_id = Column(Integer, ForeignKey("email_accounts.id"), nullable=False, index=True); started_at = Column(DateTime, default=datetime.utcnow, nullable=False); completed_at = Column(DateTime); status = Column(String(50), nullable=False, index=True); message_count = Column(Integer, default=0); success_count = Column(Integer, default=0); failure_count = Column(Integer, default=0); error_summary = Column(Text)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id = Column(Integer, primary_key=True); account_id = Column(Integer, ForeignKey("email_accounts.id"), nullable=False, index=True); batch_id = Column(Integer, ForeignKey("email_ingestion_batches.id"), nullable=True, index=True); provider_message_id = Column(String(255), nullable=False, unique=True, index=True); thread_id = Column(String(255), index=True); sender = Column(String(500)); recipients = Column(JSON); subject = Column(String(1000)); received_at = Column(DateTime, index=True); status = Column(String(50), default="Yeni", nullable=False, index=True); error_code = Column(String(100)); related_document_ids = Column(JSON); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class EmailAttachment(Base):
    __tablename__ = "email_attachments"
    id = Column(Integer, primary_key=True); message_id = Column(Integer, ForeignKey("email_messages.id"), nullable=False, index=True); provider_attachment_id = Column(String(255)); filename = Column(String(512)); mime_type = Column(String(150)); file_size = Column(Integer); file_hash = Column(String(128), nullable=False, index=True); document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True); status = Column(String(50), nullable=False, index=True); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("uq_email_attachment_message_hash", "message_id", "file_hash", unique=True),)


class EmailProcessingEvent(Base):
    __tablename__ = "email_processing_events"
    id = Column(Integer, primary_key=True); message_id = Column(Integer, ForeignKey("email_messages.id"), nullable=False, index=True); event_type = Column(String(100), nullable=False, index=True); status = Column(String(50)); details = Column(JSON); created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class WhatsAppAccount(Base):
    __tablename__ = "whatsapp_accounts"
    id = Column(Integer, primary_key=True); phone_number_id = Column(String(255), nullable=False, unique=True); display_name = Column(String(255)); is_active = Column(Boolean, default=True, nullable=False); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WhatsAppConversation(Base):
    __tablename__ = "whatsapp_conversations"
    id = Column(Integer, primary_key=True); account_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False, index=True); customer_phone = Column(String(100), nullable=False, index=True); customer_name = Column(String(255)); last_message_at = Column(DateTime, index=True); status = Column(String(50), default="Aktif", nullable=False); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("uq_whatsapp_conversation_account_phone", "account_id", "customer_phone", unique=True),)


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    id = Column(Integer, primary_key=True); conversation_id = Column(Integer, ForeignKey("whatsapp_conversations.id"), nullable=False, index=True); provider_event_id = Column(String(255), nullable=False, unique=True, index=True); provider_message_id = Column(String(255), index=True); message_type = Column(String(50), nullable=False); text_masked = Column(Text); received_at = Column(DateTime, index=True); status = Column(String(50), default="Alındı", nullable=False); raw_metadata = Column(JSON); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WhatsAppMedia(Base):
    __tablename__ = "whatsapp_media"
    id = Column(Integer, primary_key=True); message_id = Column(Integer, ForeignKey("whatsapp_messages.id"), nullable=False, index=True); provider_media_id = Column(String(255), nullable=False); mime_type = Column(String(150)); file_hash = Column(String(128), index=True); document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True); status = Column(String(50), nullable=False); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ReservationCandidate(Base):
    __tablename__ = "reservation_candidates"
    id = Column(Integer, primary_key=True); conversation_id = Column(Integer, ForeignKey("whatsapp_conversations.id"), nullable=False, index=True); source_message_id = Column(Integer, ForeignKey("whatsapp_messages.id"), nullable=False, unique=True, index=True); customer_name = Column(String(255)); phone = Column(String(100)); requested_tour = Column(String(255)); service_date = Column(DateTime); passenger_count = Column(Integer); adult_count = Column(Integer); child_count = Column(Integer); hotel = Column(String(255)); pickup_location = Column(String(500)); preferred_language = Column(String(50)); nationality = Column(String(100)); transfer_request = Column(Boolean); special_requests = Column(Text); quoted_price = Column(Numeric(18, 2)); currency = Column(String(10)); payment_information = Column(Text); confidence = Column(Numeric(5, 2), index=True); missing_fields = Column(JSON); status = Column(String(50), default="Yeni", nullable=False, index=True); booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True, index=True); created_at = Column(DateTime, default=datetime.utcnow, nullable=False); updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ReservationCandidateField(Base):
    __tablename__ = "reservation_candidate_fields"
    id = Column(Integer, primary_key=True); candidate_id = Column(Integer, ForeignKey("reservation_candidates.id"), nullable=False, index=True); field_name = Column(String(100), nullable=False); original_value = Column(JSON); corrected_value = Column(JSON); confidence = Column(Numeric(5, 2)); source_message_id = Column(Integer, ForeignKey("whatsapp_messages.id")); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ReservationCandidateEvent(Base):
    __tablename__ = "reservation_candidate_events"
    id = Column(Integer, primary_key=True); candidate_id = Column(Integer, ForeignKey("reservation_candidates.id"), nullable=False, index=True); event_type = Column(String(100), nullable=False, index=True); details = Column(JSON); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    id = Column(Integer, primary_key=True); notification_type = Column(String(100), nullable=False, index=True); channel = Column(String(50), nullable=False); language = Column(String(10), default="TR"); template_text = Column(Text, nullable=False); is_active = Column(Boolean, default=True, nullable=False); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True); notification_type = Column(String(100), nullable=False, index=True); entity_type = Column(String(100), nullable=False, index=True); entity_id = Column(Integer, nullable=False, index=True); channel = Column(String(50), nullable=False); recipient = Column(String(500)); template_id = Column(Integer, ForeignKey("notification_templates.id"), nullable=True); rendered_text = Column(Text, nullable=False); level = Column(String(50), nullable=False, index=True); scheduled_at = Column(DateTime, index=True); sent_at = Column(DateTime); due_date = Column(DateTime, index=True); status = Column(String(50), default="Planlandı", nullable=False, index=True); retry_count = Column(Integer, default=0); idempotency_key = Column(String(128), nullable=False, unique=True, index=True); is_read = Column(Boolean, default=False, nullable=False); dismissed_at = Column(DateTime); created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id = Column(Integer, primary_key=True); notification_id = Column(Integer, ForeignKey("notifications.id"), nullable=False, index=True); provider = Column(String(100), nullable=False); attempt_number = Column(Integer, nullable=False); status = Column(String(50), nullable=False, index=True); provider_response = Column(JSON); error_code = Column(String(100)); attempted_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    id = Column(Integer, primary_key=True); notification_type = Column(String(100), nullable=False, unique=True); enabled_channels = Column(JSON, nullable=False); reminder_days = Column(JSON, nullable=False); max_retries = Column(Integer, default=3); updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    id = Column(Integer, primary_key=True); notification_id = Column(Integer, ForeignKey("notifications.id"), nullable=False, index=True); event_type = Column(String(100), nullable=False, index=True); details = Column(JSON); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    id = Column(Integer, primary_key=True); job_name = Column(String(150), nullable=False, unique=True); schedule = Column(String(100), nullable=False); is_active = Column(Boolean, default=True, nullable=False); next_run_at = Column(DateTime); created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class JobRun(Base):
    __tablename__ = "job_runs"
    id = Column(Integer, primary_key=True); job_id = Column(Integer, ForeignKey("scheduled_jobs.id"), nullable=False, index=True); scheduled_time = Column(DateTime, nullable=False, index=True); started_at = Column(DateTime, nullable=False); finished_at = Column(DateTime); status = Column(String(50), nullable=False, index=True); processed_count = Column(Integer, default=0); success_count = Column(Integer, default=0); failure_count = Column(Integer, default=0); error_summary = Column(Text)
    __table_args__ = (Index("uq_job_run_job_scheduled", "job_id", "scheduled_time", unique=True),)


class JobLock(Base):
    __tablename__ = "job_locks"
    id = Column(Integer, primary_key=True); lock_name = Column(String(150), nullable=False, unique=True); owner_id = Column(String(100), nullable=False); acquired_at = Column(DateTime, nullable=False); expires_at = Column(DateTime, nullable=False, index=True)


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    product_id = Column(Integer, nullable=True)
    description = Column(String(500), nullable=True)
    quantity = Column(Numeric(18,4), default=Decimal('1.0'))
    unit = Column(String(50), nullable=True)
    unit_price = Column(Numeric(18,4), default=Decimal('0.00'))
    discount_rate = Column(Numeric(5,2), default=Decimal('0.00'))
    discount_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    tax_rate = Column(Numeric(5,2), default=Decimal('0.00'))
    tax_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    line_total = Column(Numeric(18,2), default=Decimal('0.00'))
    additional_cost = Column(Numeric(18,2), default=Decimal('0.00'))
    net_cost = Column(Numeric(18,2), default=Decimal('0.00'))
    invoice = relationship("Transaction", back_populates="items")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    code = Column(String(100), nullable=True)
    barcode = Column(String(100), nullable=True)
    name = Column(String(255), nullable=False)
    category = Column(String(200), nullable=True)
    brand = Column(String(200), nullable=True)
    unit = Column(String(50), default="ad")
    default_tax_rate = Column(Numeric(5,2), default=Decimal('18.00'))
    last_purchase_price = Column(Numeric(18,4), default=Decimal('0.00'))
    avg_purchase_price = Column(Numeric(18,4), default=Decimal('0.00'))
    last_sale_price = Column(Numeric(18,4), default=Decimal('0.00'))
    min_sale_price = Column(Numeric(18,4), default=Decimal('0.00'))
    stock = Column(Numeric(18,4), default=Decimal('0.00'))
    min_stock = Column(Numeric(18,4), default=Decimal('0.00'))
    is_active = Column(Boolean, default=True)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False)
    qty = Column(Numeric(18,4), default=Decimal('0.00'))
    movement_type = Column(String(50))  # 'in' or 'out'
    related_invoice_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SalesChannel(Base):
    __tablename__ = "sales_channels"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)


class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(String(100), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    company_name = Column(String(255), nullable=True)
    nationality = Column(String(100), nullable=True)
    document_number = Column(String(200), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(Text, nullable=True)
    birth_date = Column(DateTime, nullable=True)
    language = Column(String(50), nullable=True)
    emergency_contact = Column(String(255), nullable=True)
    billing_info = Column(Text, nullable=True)
    tax_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    kvkk_confirmed = Column(Boolean, default=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    bookings = relationship("Booking", back_populates="customer")


class Passenger(Base):
    __tablename__ = "booking_passengers"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    nationality = Column(String(100), nullable=True)
    passport_number = Column(String(200), nullable=True)
    passport_expiry = Column(DateTime, nullable=True)
    birth_date = Column(DateTime, nullable=True)
    gender = Column(String(20), nullable=True)
    passenger_type = Column(String(50), nullable=True)
    room_type = Column(String(100), nullable=True)
    pickup_point = Column(String(255), nullable=True)
    meal_preference = Column(String(200), nullable=True)
    health_notes = Column(Text, nullable=True)
    special_request = Column(Text, nullable=True)
    booking = relationship("Booking", back_populates="passengers")


class Tour(Base):
    __tablename__ = "tours"
    id = Column(Integer, primary_key=True)
    code = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    tour_type = Column(String(100), nullable=True)
    start_location = Column(String(255), nullable=True)
    end_location = Column(String(255), nullable=True)
    duration_days = Column(Integer, nullable=True)
    departure_datetime = Column(DateTime, nullable=True)
    return_datetime = Column(DateTime, nullable=True)
    capacity = Column(Integer, nullable=True)
    min_participants = Column(Integer, nullable=True)
    adult_price = Column(Numeric(18,2), default=Decimal('0.00'))
    child_price = Column(Numeric(18,2), default=Decimal('0.00'))
    infant_price = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    default_guide = Column(String(255), nullable=True)
    default_vehicle = Column(String(255), nullable=True)
    included_services = Column(Text, nullable=True)
    excluded_services = Column(Text, nullable=True)
    cancellation_policy = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(100), default="Taslak")
    is_active = Column(Boolean, default=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    departures = relationship("TourDeparture", back_populates="tour")
    cost_items = relationship("TourCostItem", back_populates="tour")
    bookings = relationship("Booking", back_populates="tour")


class TourDeparture(Base):
    __tablename__ = "tour_departures"
    id = Column(Integer, primary_key=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=False)
    departure_datetime = Column(DateTime, nullable=True)
    return_datetime = Column(DateTime, nullable=True)
    seats_available = Column(Integer, nullable=True)
    status = Column(String(100), nullable=True)
    tour = relationship("Tour", back_populates="departures")


class TourCostItem(Base):
    __tablename__ = "tour_cost_items"
    id = Column(Integer, primary_key=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    cost_type = Column(String(100), nullable=True)
    classification = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    unit_count = Column(Integer, nullable=True)
    unit_type = Column(String(100), nullable=True)
    is_fixed = Column(Boolean, default=False)
    tour = relationship("Tour", back_populates="cost_items")


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    booking_number = Column(String(100), nullable=False)
    booking_date = Column(DateTime, default=datetime.utcnow)
    service_start_date = Column(DateTime, nullable=True)
    service_end_date = Column(DateTime, nullable=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=True)
    booking_type = Column(String(100), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    passenger_count = Column(Integer, default=0)
    adult_count = Column(Integer, default=0)
    child_count = Column(Integer, default=0)
    infant_count = Column(Integer, default=0)
    sales_channel_id = Column(Integer, ForeignKey("sales_channels.id"), nullable=True)
    sales_person_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    guide_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    unit_price = Column(Numeric(18,2), default=Decimal('0.00'))
    total_price = Column(Numeric(18,2), default=Decimal('0.00'))
    discount_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    commission_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    tax_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    grand_total = Column(Numeric(18,2), default=Decimal('0.00'))
    deposit_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    collected_total = Column(Numeric(18,2), default=Decimal('0.00'))
    remaining_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    payment_method = Column(String(100), nullable=True)
    final_payment_date = Column(DateTime, nullable=True)
    booking_status = Column(String(100), nullable=True)
    operation_status = Column(String(100), nullable=True)
    voucher_number = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    is_demo = Column(Boolean, default=False, nullable=False)
    passengers = relationship("Passenger", back_populates="booking")
    customer = relationship("Customer", back_populates="bookings")
    bookings_services = relationship("BookingService", back_populates="booking")
    collections = relationship("Collection", back_populates="booking")
    vouchers = relationship("Voucher", back_populates="booking")
    tour = relationship("Tour", back_populates="bookings")


class BookingService(Base):
    __tablename__ = "booking_services"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    service_type = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Numeric(18,2), default=Decimal('0.00'))
    total_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    booking = relationship("Booking", back_populates="bookings_services")


class Hotel(Base):
    __tablename__ = "hotels"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    address = Column(Text, nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    currency = Column(String(10), default="TRY")
    rating = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    hotel_bookings = relationship("HotelBooking", back_populates="hotel")


class HotelBooking(Base):
    __tablename__ = "hotel_bookings"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=False)
    checkin_date = Column(DateTime, nullable=True)
    checkout_date = Column(DateTime, nullable=True)
    nights = Column(Integer, default=0)
    room_count = Column(Integer, default=0)
    room_type = Column(String(100), nullable=True)
    board_type = Column(String(100), nullable=True)
    adult_count = Column(Integer, default=0)
    child_count = Column(Integer, default=0)
    infant_count = Column(Integer, default=0)
    price_per_room = Column(Numeric(18,2), default=Decimal('0.00'))
    price_per_person = Column(Numeric(18,2), default=Decimal('0.00'))
    extra_bed = Column(Numeric(18,2), default=Decimal('0.00'))
    discount_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    tax_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    total_cost = Column(Numeric(18,2), default=Decimal('0.00'))
    cancellation_policy = Column(Text, nullable=True)
    free_cancellation_until = Column(DateTime, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    booking = relationship("Booking")
    hotel = relationship("Hotel", back_populates="hotel_bookings")


class Transfer(Base):
    __tablename__ = "transfers"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=True)
    transfer_type = Column(String(100), nullable=True)
    pickup_location = Column(String(255), nullable=True)
    dropoff_location = Column(String(255), nullable=True)
    flight_number = Column(String(100), nullable=True)
    flight_time = Column(DateTime, nullable=True)
    pickup_time = Column(DateTime, nullable=True)
    passenger_count = Column(Integer, default=0)
    vehicle_type = Column(String(100), nullable=True)
    vehicle_plate = Column(String(100), nullable=True)
    driver = Column(String(255), nullable=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    purchase_cost = Column(Numeric(18,2), default=Decimal('0.00'))
    sale_price = Column(Numeric(18,2), default=Decimal('0.00'))
    payment_status = Column(String(100), nullable=True)
    operation_status = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)


class Guide(Base):
    __tablename__ = "guides"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    languages = Column(String(255), nullable=True)
    license_number = Column(String(200), nullable=True)
    specialties = Column(Text, nullable=True)
    daily_fee = Column(Numeric(18,2), default=Decimal('0.00'))
    half_day_fee = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    iban = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)


class GuideAssignment(Base):
    __tablename__ = "guide_assignments"
    id = Column(Integer, primary_key=True)
    guide_id = Column(Integer, ForeignKey("guides.id"), nullable=False)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    assigned_date = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)
    guide = relationship("Guide")


class Collection(Base):
    __tablename__ = "collections"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    collection_date = Column(DateTime, default=datetime.utcnow)
    amount = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    amount_in_tl = Column(Numeric(18,2), default=Decimal('0.00'))
    payment_method = Column(String(100), nullable=True)
    account_name = Column(String(255), nullable=True)
    transaction_reference = Column(String(255), nullable=True)
    receipt_number = Column(String(255), nullable=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    notes = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    booking = relationship("Booking", back_populates="collections")


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    supplier_type = Column(String(100), nullable=True)
    contact_person = Column(String(255), nullable=True)
    tax_office = Column(String(100), nullable=True)
    tax_number = Column(String(100), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(Text, nullable=True)
    iban = Column(String(200), nullable=True)
    currency = Column(String(10), default="TRY")
    payment_terms = Column(String(255), nullable=True)
    average_payment_days = Column(Integer, nullable=True)
    risk_limit = Column(String(100), nullable=True)
    contract_start = Column(DateTime, nullable=True)
    contract_end = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)


class SupplierPayment(Base):
    __tablename__ = "supplier_payments"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=True)
    invoice_reference = Column(String(255), nullable=True)
    service_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    payment_date = Column(DateTime, nullable=True)
    total_debt = Column(Numeric(18,2), default=Decimal('0.00'))
    paid_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    remaining_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    payment_method = Column(String(100), nullable=True)
    account_name = Column(String(255), nullable=True)
    payment_status = Column(String(100), nullable=True)
    document_reference = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)


class SupplierContract(Base):
    __tablename__ = "supplier_contracts"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    contract_number = Column(String(100), nullable=False, index=True)
    supplier_type = Column(String(50), nullable=False, index=True)
    valid_from = Column(DateTime, nullable=False, index=True)
    valid_to = Column(DateTime, nullable=False, index=True)
    currency = Column(String(10), nullable=False, default="TRY")
    payment_terms_days = Column(Integer, default=0, nullable=False)
    cancellation_rule = Column(Text)
    free_person_rule = Column(JSON)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SupplierContractPrice(Base):
    __tablename__ = "supplier_contract_prices"
    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("supplier_contracts.id"), nullable=False, index=True)
    service_code = Column(String(100), nullable=False, index=True)
    service_name = Column(String(255), nullable=False)
    expense_category = Column(String(100), nullable=False, index=True)
    pricing_unit = Column(String(50), nullable=False)
    unit_price = Column(Numeric(18, 2), nullable=False)
    tax_rate = Column(Numeric(8, 4), default=Decimal("0"), nullable=False)
    minimum_quantity = Column(Integer, default=0, nullable=False)
    rules = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("uq_contract_service_code", "contract_id", "service_code", unique=True),)


class TourBudget(Base):
    __tablename__ = "tour_budgets"
    id = Column(Integer, primary_key=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    passenger_target = Column(Integer, default=0, nullable=False)
    currency = Column(String(10), default="TRY", nullable=False)
    exchange_rate = Column(Numeric(18, 6), default=Decimal("1"), nullable=False)
    status = Column(String(50), default="Aktif", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TourBudgetLine(Base):
    __tablename__ = "tour_budget_lines"
    id = Column(Integer, primary_key=True)
    budget_id = Column(Integer, ForeignKey("tour_budgets.id"), nullable=False, index=True)
    line_type = Column(String(20), nullable=False, index=True)
    category = Column(String(100), nullable=False, index=True)
    description = Column(String(500))
    quantity = Column(Numeric(18, 4), default=Decimal("1"), nullable=False)
    unit_amount = Column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    is_variable = Column(Boolean, default=False, nullable=False)
    contract_price_id = Column(Integer, ForeignKey("supplier_contract_prices.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AccountReconciliationRun(Base):
    __tablename__ = "account_reconciliation_runs"
    id = Column(Integer, primary_key=True)
    party_type = Column(String(20), nullable=False, index=True)
    party_id = Column(Integer, nullable=False, index=True)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    currency = Column(String(10), nullable=False)
    opening_balance = Column(Numeric(18, 2), nullable=False)
    invoice_total = Column(Numeric(18, 2), nullable=False)
    payment_total = Column(Numeric(18, 2), nullable=False)
    credit_total = Column(Numeric(18, 2), nullable=False)
    closing_balance = Column(Numeric(18, 2), nullable=False)
    status = Column(String(50), default="Hesaplandı", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AccountReconciliationLine(Base):
    __tablename__ = "account_reconciliation_lines"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("account_reconciliation_runs.id"), nullable=False, index=True)
    entry_date = Column(DateTime, nullable=False, index=True)
    entry_type = Column(String(30), nullable=False)
    reference = Column(String(255))
    description = Column(Text)
    debit = Column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    credit = Column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    running_balance = Column(Numeric(18, 2), nullable=False)
    source_entity_type = Column(String(100))
    source_entity_id = Column(Integer)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    id = Column(Integer, primary_key=True)
    rate_date = Column(DateTime, nullable=False, index=True)
    currency = Column(String(10), nullable=False, index=True)
    try_rate = Column(Numeric(18, 6), nullable=False)
    source = Column(String(100), default="Manuel", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("uq_exchange_rate_date_currency", "rate_date", "currency", unique=True),)


class CurrencySettlement(Base):
    __tablename__ = "currency_settlements"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    direction = Column(String(20), nullable=False)
    currency = Column(String(10), nullable=False, index=True)
    foreign_amount = Column(Numeric(18, 2), nullable=False)
    recognition_rate = Column(Numeric(18, 6), nullable=False)
    settlement_rate = Column(Numeric(18, 6), nullable=False)
    recognition_try = Column(Numeric(18, 2), nullable=False)
    settlement_try = Column(Numeric(18, 2), nullable=False)
    exchange_difference = Column(Numeric(18, 2), nullable=False)
    settlement_date = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("uq_currency_settlement_entity", "entity_type", "entity_id", unique=True),)


class CashAccount(Base):
    __tablename__ = "cash_accounts"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    currency = Column(String(10), default="TRY")
    balance = Column(Numeric(18,2), default=Decimal('0.00'))
    notes = Column(Text, nullable=True)


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    id = Column(Integer, primary_key=True)
    bank_name = Column(String(255), nullable=False)
    branch = Column(String(255), nullable=True)
    iban = Column(String(255), nullable=True)
    account_number = Column(String(100), nullable=True)
    currency = Column(String(10), default="TRY")
    balance = Column(Numeric(18,2), default=Decimal('0.00'))
    notes = Column(Text, nullable=True)


class CurrencyRate(Base):
    __tablename__ = "currency_rates"
    id = Column(Integer, primary_key=True)
    currency = Column(String(10), nullable=False)
    rate = Column(Numeric(18,6), default=Decimal('1.0'))
    date = Column(DateTime, default=datetime.utcnow)


class Cancellation(Base):
    __tablename__ = "cancellations"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    cancellation_date = Column(DateTime, default=datetime.utcnow)
    reason = Column(Text, nullable=True)
    customer_refund = Column(Numeric(18,2), default=Decimal('0.00'))
    cancellation_fee = Column(Numeric(18,2), default=Decimal('0.00'))
    supplier_refund = Column(Numeric(18,2), default=Decimal('0.00'))
    supplier_penalty = Column(Numeric(18,2), default=Decimal('0.00'))
    net_cancel_result = Column(Numeric(18,2), default=Decimal('0.00'))
    refund_method = Column(String(100), nullable=True)
    document_reference = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)


class Refund(Base):
    __tablename__ = "refunds"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    refund_date = Column(DateTime, default=datetime.utcnow)
    amount = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    refund_method = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)


class Voucher(Base):
    __tablename__ = "vouchers"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    voucher_number = Column(String(200), nullable=True)
    issue_date = Column(DateTime, default=datetime.utcnow)
    customer_name = Column(String(255), nullable=True)
    service_name = Column(String(255), nullable=True)
    travel_date = Column(DateTime, nullable=True)
    pickup_location = Column(String(255), nullable=True)
    dropoff_location = Column(String(255), nullable=True)
    hotel_info = Column(Text, nullable=True)
    transfer_info = Column(Text, nullable=True)
    guide_info = Column(Text, nullable=True)
    included_services = Column(Text, nullable=True)
    excluded_services = Column(Text, nullable=True)
    emergency_contact = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    booking = relationship("Booking", back_populates="vouchers")
