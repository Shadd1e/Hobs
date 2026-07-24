"""add onboarding columns to clients table

Revision ID: 0016_onboarding_columns
Revises: 0015
Create Date: 2026-05-12

Adds three columns needed for the WhatsApp number onboarding flow:
  - onboarding_status           : tracks where the merchant is in the activation process
  - pending_otp_code            : temporarily stores the 6-digit code the merchant submits
  - number_submission_attempts  : rate-limits how many times they can change their number
"""
from alembic import op
import sqlalchemy as sa

revision      = "0016_onboarding_columns"
down_revision = "0015"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column(
            "onboarding_status",
            sa.String(30),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "clients",
        sa.Column(
            "pending_otp_code",
            sa.String(6),
            nullable=True,
        ),
    )
    op.add_column(
        "clients",
        sa.Column(
            "number_submission_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Index for fast status lookups (admin panel filtering)
    op.create_index(
        "ix_clients_onboarding_status",
        "clients",
        ["onboarding_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_clients_onboarding_status", table_name="clients")
    op.drop_column("clients", "number_submission_attempts")
    op.drop_column("clients", "pending_otp_code")
    op.drop_column("clients", "onboarding_status")
