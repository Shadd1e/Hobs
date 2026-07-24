"""expand merchant and client ID columns from VARCHAR(6) to VARCHAR(20)

Revision ID: 0002_fix_id_column_lengths
Revises: 0001_initial
Create Date: 2026-04-25

Merchant IDs are now MX + 6 random alphanumeric chars (8 chars total).
Store IDs are now ST + 6 random alphanumeric chars (8 chars total).
VARCHAR(20) gives plenty of headroom for future format changes.
"""
from alembic import op

revision = "0002_fix_id_column_lengths"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand primary keys first, then all FK/plain columns that reference them.
    # PostgreSQL allows widening VARCHAR without dropping FK constraints.

    # ── Primary keys ──────────────────────────────────────────────────────────
    op.execute("ALTER TABLE merchants ALTER COLUMN id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE clients ALTER COLUMN id TYPE VARCHAR(20)")

    # ── clients ───────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE clients ALTER COLUMN merchant_id TYPE VARCHAR(20)")

    # ── client_whatsapp_credentials ───────────────────────────────────────────
    op.execute("ALTER TABLE client_whatsapp_credentials ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── customer_profiles ─────────────────────────────────────────────────────
    op.execute("ALTER TABLE customer_profiles ALTER COLUMN last_order_client_id TYPE VARCHAR(20)")

    # ── idempotency_keys ──────────────────────────────────────────────────────
    op.execute("ALTER TABLE idempotency_keys ALTER COLUMN merchant_id TYPE VARCHAR(20)")

    # ── products ──────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE products ALTER COLUMN merchant_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE products ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── carts ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE carts ALTER COLUMN merchant_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE carts ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── inventories ───────────────────────────────────────────────────────────
    op.execute("ALTER TABLE inventories ALTER COLUMN merchant_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE inventories ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── orders ────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE orders ALTER COLUMN merchant_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE orders ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── payments ──────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE payments ALTER COLUMN merchant_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE payments ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── clarifications ────────────────────────────────────────────────────────
    op.execute("ALTER TABLE clarifications ALTER COLUMN merchant_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE clarifications ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── human_agent_tasks ─────────────────────────────────────────────────────
    op.execute("ALTER TABLE human_agent_tasks ALTER COLUMN client_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE human_agent_tasks ALTER COLUMN merchant_id TYPE VARCHAR(20)")

    # ── webhook_events ────────────────────────────────────────────────────────
    op.execute("ALTER TABLE webhook_events ALTER COLUMN merchant_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE webhook_events ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── deepseek_settings ─────────────────────────────────────────────────────
    op.execute("ALTER TABLE deepseek_settings ALTER COLUMN client_id TYPE VARCHAR(20)")

    # ── flutterwave_subaccounts ───────────────────────────────────────────────
    op.execute("ALTER TABLE flutterwave_subaccounts ALTER COLUMN client_id TYPE VARCHAR(20)")
    op.execute("ALTER TABLE flutterwave_subaccounts ALTER COLUMN merchant_id TYPE VARCHAR(20)")


def downgrade() -> None:
    # Only safe if all existing IDs are still ≤ 6 chars.
    op.execute("ALTER TABLE flutterwave_subaccounts ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE flutterwave_subaccounts ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE deepseek_settings ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE webhook_events ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE webhook_events ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE human_agent_tasks ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE human_agent_tasks ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE clarifications ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE clarifications ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE payments ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE payments ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE orders ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE orders ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE inventories ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE inventories ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE carts ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE carts ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE products ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE products ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE idempotency_keys ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE customer_profiles ALTER COLUMN last_order_client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE client_whatsapp_credentials ALTER COLUMN client_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE clients ALTER COLUMN merchant_id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE clients ALTER COLUMN id TYPE VARCHAR(6)")
    op.execute("ALTER TABLE merchants ALTER COLUMN id TYPE VARCHAR(6)")
