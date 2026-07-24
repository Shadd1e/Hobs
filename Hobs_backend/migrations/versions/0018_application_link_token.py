"""add link_token to merchant_applications, make whatsapp_number nullable

Revision ID: 0018_application_link_token
Revises: 0017_merchant_applications
Create Date: 2026-06-17

Two changes to support optional WhatsApp number at application time:
  - whatsapp_number is now nullable (the apply form no longer requires it)
  - link_token: a dedicated, unguessable public token used by the
    "add my WhatsApp number" follow-up page — deliberately separate from
    the human-readable `id` column, which already appears in Slack/admin UI
    and shouldn't double as a bearer credential.
"""
from alembic import op
import sqlalchemy as sa

revision      = "0018_application_link_token"
down_revision = "0017_merchant_applications"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.alter_column(
        "merchant_applications", "whatsapp_number",
        existing_type=sa.String(30), nullable=True,
    )
    op.add_column(
        "merchant_applications",
        sa.Column("link_token", sa.String(48), nullable=True),
    )
    op.add_column(
        "merchant_applications",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_merchant_applications_link_token",
        "merchant_applications", ["link_token"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_merchant_applications_link_token", table_name="merchant_applications")
    op.drop_column("merchant_applications", "last_error")
    op.drop_column("merchant_applications", "link_token")
    op.alter_column(
        "merchant_applications", "whatsapp_number",
        existing_type=sa.String(30), nullable=False,
    )
