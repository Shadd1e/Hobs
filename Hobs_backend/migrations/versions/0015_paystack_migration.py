"""paystack migration — add provider column to subaccounts

Revision ID: 0015
Revises: 0014_customer_last_order
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014_customer_last_order"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "flutterwave_subaccounts",
        sa.Column("provider", sa.String(20), nullable=True, server_default="paystack")
    )


def downgrade():
    op.drop_column("flutterwave_subaccounts", "provider")
