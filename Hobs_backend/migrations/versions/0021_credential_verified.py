"""add verified column to client_whatsapp_credentials

Revision ID: 0021_credential_verified
Revises: 0020_onboarding_wizard
Create Date: 2026-06-26

Client.is_whatsapp_verified (models/client_model.py) reads
self.whatsapp_credential.verified, but client_whatsapp_credentials never
had a `verified` column in 0001_initial or any later migration — that
property has been broken since it was written.

Set True once Meta's /verify_code call succeeds
(api/v1/admin_whatsapp.py verify_otp), via
ClientWhatsAppCredential.mark_otp_verified(). Distinct from `active`,
which additionally requires /register + webhook subscription to have
completed afterwards — a credential can be verified=True and active=False
at the same time, during the otp_verified state.
"""
from alembic import op
import sqlalchemy as sa

revision      = "0021_credential_verified"
down_revision = "0020_onboarding_wizard"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        "client_whatsapp_credentials",
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="True once Meta's /verify_code succeeds. See ClientWhatsAppCredential.mark_otp_verified().",
        ),
    )
    op.create_index(
        "ix_cwc_verified",
        "client_whatsapp_credentials",
        ["verified"],
    )


def downgrade() -> None:
    op.drop_index("ix_cwc_verified", table_name="client_whatsapp_credentials")
    op.drop_column("client_whatsapp_credentials", "verified")
