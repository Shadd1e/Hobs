"""add must_change_password to merchants

Revision ID: 0019_must_change_password
Revises: 0018_application_link_token
Create Date: 2026-06-19

Set True when admin creates an account with a generated password.
Cleared the moment the merchant completes their first password reset.
Prevents the auto-generated initial password from being used indefinitely.
"""
from alembic import op
import sqlalchemy as sa

revision      = "0019_must_change_password"
down_revision = "0018_application_link_token"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        "merchants",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="True = account was created with a generated password that must be changed on first login.",
        ),
    )


def downgrade() -> None:
    op.drop_column("merchants", "must_change_password")
