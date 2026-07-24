"""create merchant_applications table

Revision ID: 0017_merchant_applications
Revises: 0016_onboarding_columns
Create Date: 2026-06-17

Persists every "Apply to Use" submission so it shows up in the admin
WhatsApp-setup dashboard until reviewed, instead of only firing an email +
Slack alert and discarding the data (which was the previous behaviour).
"""
from alembic import op
import sqlalchemy as sa

revision      = "0017_merchant_applications"
down_revision = "0016_onboarding_columns"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "merchant_applications",
        sa.Column("id", sa.String(20), primary_key=True),

        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("business_type", sa.String(100), nullable=False),
        sa.Column("city_state", sa.String(150), nullable=False),

        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(30), nullable=False),
        sa.Column("whatsapp_number", sa.String(30), nullable=False),

        sa.Column("num_branches", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("monthly_order_volume", sa.String(50), nullable=True),
        sa.Column("uses_whatsapp_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uses_delivery_service", sa.Boolean(), nullable=False, server_default=sa.false()),

        sa.Column("heard_about_us", sa.String(200), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),

        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("merchant_id", sa.String(20), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_merchant_applications_email", "merchant_applications", ["email"])
    op.create_index("ix_merchant_applications_status", "merchant_applications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_merchant_applications_status", table_name="merchant_applications")
    op.drop_index("ix_merchant_applications_email", table_name="merchant_applications")
    op.drop_table("merchant_applications")
