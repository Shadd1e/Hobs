"""add onboarding wizard columns to merchant_applications

Revision ID: 0020_onboarding_wizard
Revises: 0019_must_change_password
Create Date: 2026-06-23

Supports the 4-step resumable "Apply to Use" wizard (name/contact ->
business details -> verification -> terms/indemnity):

  - business_name / business_type / city_state are now nullable, since a
    draft row is created after step 1 (name + contact only) and those
    fields aren't filled in until step 2.
  - registration_status: "registered" | "unregistered" — chosen in step 2,
    decides which verification path step 3 takes.
  - cac_number / bvn / nin: encrypted at the application layer (see
    app/core/crypto.py EncryptedString) — stored as ciphertext, so the
    column is sized generously beyond the raw value length.
  - verification_method / verification_status / verification_name_on_file:
    track which check ran and what it returned.
  - transaction_limit: set once verification completes; depends on
    registered vs unregistered and verified vs pending_manual_review.
  - terms_version / terms_accepted_at / terms_accepted_ip: audit trail for
    the indemnity + terms acceptance in step 4 — not just a boolean, so a
    later dispute can show exactly what they agreed to and when.
  - resume_token / resume_token_expires_at: the "continue later" link,
    deliberately separate from `link_token` (which still backs the older
    add-WhatsApp-number-later flow on already-submitted applications).
  - current_step / last_activity_at / reminder_count / last_reminder_sent_at:
    drive the resumable wizard UI and the idle-draft reminder job.
"""
from alembic import op
import sqlalchemy as sa

revision      = "0020_onboarding_wizard"
down_revision = "0019_must_change_password"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # Step 2+ fields — nullable now that a draft can exist before they're filled in.
    op.alter_column("merchant_applications", "business_name", existing_type=sa.String(255), nullable=True)
    op.alter_column("merchant_applications", "business_type", existing_type=sa.String(100), nullable=True)
    op.alter_column("merchant_applications", "city_state",    existing_type=sa.String(150), nullable=True)

    op.add_column("merchant_applications", sa.Column("registration_status", sa.String(20), nullable=True,
        comment="registered | unregistered — set in step 2, decides the step-3 verification path."))

    # Encrypted at the app layer — ciphertext is longer than the raw value, hence String(500).
    op.add_column("merchant_applications", sa.Column("cac_number", sa.String(500), nullable=True))
    op.add_column("merchant_applications", sa.Column("bvn", sa.String(500), nullable=True))
    op.add_column("merchant_applications", sa.Column("nin", sa.String(500), nullable=True))

    op.add_column("merchant_applications", sa.Column("verification_method", sa.String(20), nullable=True,
        comment="cac | bvn | nin"))
    op.add_column("merchant_applications", sa.Column("verification_status", sa.String(30), nullable=True,
        comment="not_started | pending_manual_review | verified | failed"))
    op.add_column("merchant_applications", sa.Column("verification_name_on_file", sa.String(255), nullable=True,
        comment="Name returned by the verification provider — checked against full_name."))

    op.add_column("merchant_applications", sa.Column("transaction_limit", sa.Numeric(12, 2), nullable=True))

    op.add_column("merchant_applications", sa.Column("terms_version", sa.String(20), nullable=True))
    op.add_column("merchant_applications", sa.Column("terms_accepted", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("merchant_applications", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("merchant_applications", sa.Column("terms_accepted_ip", sa.String(64), nullable=True))

    op.add_column("merchant_applications", sa.Column("resume_token", sa.String(48), nullable=True))
    op.add_column("merchant_applications", sa.Column("resume_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_merchant_applications_resume_token", "merchant_applications", ["resume_token"], unique=True)

    op.add_column("merchant_applications", sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("merchant_applications", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("merchant_applications", sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("merchant_applications", sa.Column("last_reminder_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("merchant_applications", "last_reminder_sent_at")
    op.drop_column("merchant_applications", "reminder_count")
    op.drop_column("merchant_applications", "last_activity_at")
    op.drop_column("merchant_applications", "current_step")
    op.drop_index("ix_merchant_applications_resume_token", table_name="merchant_applications")
    op.drop_column("merchant_applications", "resume_token_expires_at")
    op.drop_column("merchant_applications", "resume_token")
    op.drop_column("merchant_applications", "terms_accepted_ip")
    op.drop_column("merchant_applications", "terms_accepted_at")
    op.drop_column("merchant_applications", "terms_accepted")
    op.drop_column("merchant_applications", "terms_version")
    op.drop_column("merchant_applications", "transaction_limit")
    op.drop_column("merchant_applications", "verification_name_on_file")
    op.drop_column("merchant_applications", "verification_status")
    op.drop_column("merchant_applications", "verification_method")
    op.drop_column("merchant_applications", "nin")
    op.drop_column("merchant_applications", "bvn")
    op.drop_column("merchant_applications", "cac_number")
    op.drop_column("merchant_applications", "registration_status")
    op.alter_column("merchant_applications", "city_state",    existing_type=sa.String(150), nullable=False)
    op.alter_column("merchant_applications", "business_type", existing_type=sa.String(100), nullable=False)
    op.alter_column("merchant_applications", "business_name", existing_type=sa.String(255), nullable=False)
