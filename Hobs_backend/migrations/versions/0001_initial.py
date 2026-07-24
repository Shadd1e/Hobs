"""initial schema — all tables from scratch

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enum types (idempotent via exception handler) ──────────────────────────
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE order_status AS ENUM (
                'CREATED', 'PENDING_PAYMENT', 'PAID',
                'OUT_FOR_DELIVERY', 'AWAITING_PICKUP',
                'FULFILLED', 'CANCELLED', 'REFUNDED'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE deliverytype AS ENUM ('pickup', 'delivery');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE payment_status_enum AS ENUM (
                'PENDING', 'SUCCEEDED', 'FAILED', 'REFUNDED'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE whatsapp_message_direction AS ENUM ('incoming', 'outgoing');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ── 1. merchants ───────────────────────────────────────────────────────────
    op.create_table(
        "merchants",
        sa.Column("id", sa.String(6), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_verification_token", sa.String(64), nullable=True),
        sa.Column("email_verification_token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waba_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("whatsapp_number", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("email", name="uq_merchants_email"),
    )
    op.create_index("ix_merchants_id", "merchants", ["id"])
    op.create_index("ix_merchants_email_verification_token", "merchants", ["email_verification_token"])

    # ── 2. clients ─────────────────────────────────────────────────────────────
    op.create_table(
        "clients",
        sa.Column("id", sa.String(6), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("whatsapp_number", sa.String(20), nullable=True),
        sa.Column("store_contact_number", sa.String(20), nullable=True),
        sa.Column("operator_notify_phone", sa.String(20), nullable=True),
        sa.Column("delivery_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("delivery_fee", sa.Numeric(10, 2), nullable=True),
        sa.Column("assistant_name", sa.String(80), nullable=True),
        sa.Column("assistant_personality", sa.String(30), nullable=True),
        sa.Column("client_changes_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("opens_at", sa.String(5), nullable=True),
        sa.Column("closes_at", sa.String(5), nullable=True),
        sa.Column("store_timezone", sa.String(50), nullable=True, server_default=sa.text("'Africa/Lagos'")),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_clients_id", "clients", ["id"])
    op.create_index("ix_clients_merchant_id", "clients", ["merchant_id"])

    # ── 3. customer_profiles ───────────────────────────────────────────────────
    op.create_table(
        "customer_profiles",
        sa.Column("phone_number", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("last_order_summary", sa.Text(), nullable=True),
        sa.Column("last_order_client_id", sa.String(6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── 4. idempotency_keys ────────────────────────────────────────────────────
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(6), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=True),
        sa.Column("response_data", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_headers", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("is_processing", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("merchant_id", "key", name="uq_idempotency_merchant_key"),
    )
    op.create_index("ix_idempotency_keys_merchant_id", "idempotency_keys", ["merchant_id"])
    op.create_index("ix_idempotency_keys_key", "idempotency_keys", ["key"])
    op.create_index("ix_idempotency_merchant_key_expires", "idempotency_keys", ["merchant_id", "key", "expires_at"])

    # ── 5. whatsapp_message_logs ───────────────────────────────────────────────
    # No FKs — standalone audit log table
    op.create_table(
        "whatsapp_message_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("merchant_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=True),
        sa.Column("from_number", sa.String(), nullable=False),
        sa.Column("to_number", sa.String(), nullable=True),
        sa.Column(
            "direction",
            postgresql.ENUM(
                "incoming", "outgoing",
                name="whatsapp_message_direction",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("meta", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── 6. client_whatsapp_credentials ────────────────────────────────────────
    op.create_table(
        "client_whatsapp_credentials",
        sa.Column(
            "client_id",
            sa.String(6),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("phone_number_id", sa.String(255), nullable=False),
        sa.Column("whatsapp_number", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("phone_number_id", name="uq_cwc_phone_number_id"),
    )
    op.create_index("ix_cwc_client_id", "client_whatsapp_credentials", ["client_id"])
    op.create_index("ix_cwc_phone_number_id", "client_whatsapp_credentials", ["phone_number_id"], unique=True)
    op.create_index("ix_cwc_status", "client_whatsapp_credentials", ["status"])
    op.create_index("ix_cwc_active", "client_whatsapp_credentials", ["active"])

    # ── 7. products ────────────────────────────────────────────────────────────
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("variant_group", sa.String(100), nullable=True),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_products_merchant_id", "products", ["merchant_id"])
    op.create_index("ix_products_client_id", "products", ["client_id"])
    op.create_index("ix_products_variant_group", "products", ["client_id", "variant_group"])
    op.create_index("ix_products_category", "products", ["client_id", "category"])

    # ── 8. carts ───────────────────────────────────────────────────────────────
    op.create_table(
        "carts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_out", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "merchant_id", "client_id", "user_id", "checked_out",
            name="uq_active_cart_per_user",
        ),
    )
    op.create_index("ix_carts_merchant_id", "carts", ["merchant_id"])
    op.create_index("ix_carts_client_id", "carts", ["client_id"])
    op.create_index("ix_carts_user_id", "carts", ["user_id"])
    op.create_index("ix_carts_merchant_client_user", "carts", ["merchant_id", "client_id", "user_id"])
    op.create_index("ix_carts_checked_out", "carts", ["checked_out"])
    op.create_index("ix_carts_user_created", "carts", ["user_id", "created_at"])
    op.create_index("ix_cart_lookup", "carts", ["merchant_id", "client_id", "user_id", "checked_out"])

    # ── 9. inventories ─────────────────────────────────────────────────────────
    op.create_table(
        "inventories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("warehouse_location", sa.String(255), nullable=True),
        sa.UniqueConstraint(
            "product_id", "merchant_id", "client_id",
            name="uq_inventory_per_tenant_product",
        ),
    )
    op.create_index("ix_inventories_product_id", "inventories", ["product_id"])
    op.create_index("ix_inventories_merchant_id", "inventories", ["merchant_id"])
    op.create_index("ix_inventories_client_id", "inventories", ["client_id"])
    op.create_index("ix_inventory_tenant_product", "inventories", ["merchant_id", "client_id", "product_id"])

    # ── 10. cart_items ─────────────────────────────────────────────────────────
    op.create_table(
        "cart_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cart_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_at_add", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cart_id", "product_id", name="uq_cart_product"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_product", "cart_items", ["product_id"])
    op.create_index("ix_cart_items_cart_created", "cart_items", ["cart_id", "created_at"])

    # ── 11. orders ─────────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_code", sa.String(8), nullable=False),
        sa.Column(
            "cart_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("customer_name", sa.String(100), nullable=True),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "CREATED", "PENDING_PAYMENT", "PAID",
                "OUT_FOR_DELIVERY", "AWAITING_PICKUP",
                "FULFILLED", "CANCELLED", "REFUNDED",
                name="order_status",
                create_type=False,
            ),
            nullable=False,
            server_default="CREATED",
        ),
        sa.Column(
            "delivery_type",
            postgresql.ENUM("pickup", "delivery", name="deliverytype", create_type=False),
            nullable=True,
        ),
        sa.Column("delivery_address", sa.Text(), nullable=True),
        sa.Column("delivery_contact_number", sa.String(20), nullable=True),
        sa.Column("delivery_fee", sa.Numeric(10, 2), nullable=True),
        # SQLAlchemy model names this attribute order_metadata but the DB column is "metadata"
        sa.Column("metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("order_code", name="uq_orders_order_code"),
        sa.UniqueConstraint("cart_id", name="uq_order_per_cart"),
    )
    op.create_index("ix_orders_order_code", "orders", ["order_code"], unique=True)
    op.create_index("ix_orders_cart_id", "orders", ["cart_id"], unique=True)
    op.create_index("ix_orders_merchant_id", "orders", ["merchant_id"])
    op.create_index("ix_orders_client_id", "orders", ["client_id"])
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_payment_method", "orders", ["payment_method"])
    op.create_index("ix_orders_merchant_client", "orders", ["merchant_id", "client_id"])
    op.create_index("ix_orders_user_status", "orders", ["user_id", "status"])
    op.create_index("ix_orders_merchant_status", "orders", ["merchant_id", "status"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])
    op.create_index("ix_orders_order_code_lookup", "orders", ["order_code", "merchant_id"])

    # ── 12. payments ───────────────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING", "SUCCEEDED", "FAILED", "REFUNDED",
                name="payment_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("external_reference", sa.String(128), nullable=True),
        sa.Column("payment_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("order_id", name="uq_payment_per_order"),
        sa.UniqueConstraint("external_reference", name="uq_payments_external_reference"),
    )
    op.create_index("ix_payments_id", "payments", ["id"])
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_merchant_id", "payments", ["merchant_id"])
    op.create_index("ix_payments_client_id", "payments", ["client_id"])
    op.create_index("ix_payment_external_reference", "payments", ["external_reference"])
    op.create_index("ix_payment_merchant_client", "payments", ["merchant_id", "client_id"])

    # ── 13. clarifications ─────────────────────────────────────────────────────
    op.create_table(
        "clarifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_clarifications_id", "clarifications", ["id"])

    # ── 14. human_agent_tasks ──────────────────────────────────────────────────
    op.create_table(
        "human_agent_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "cart_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=True, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_human_agent_tasks_cart_id", "human_agent_tasks", ["cart_id"])
    op.create_index("ix_human_agent_tasks_client_id", "human_agent_tasks", ["client_id"])
    op.create_index("ix_human_agent_tasks_merchant_id", "human_agent_tasks", ["merchant_id"])

    # ── 15. webhook_events ─────────────────────────────────────────────────────
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone_number_id", sa.String(255), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_webhook_events_provider", "webhook_events", ["provider"])
    op.create_index("ix_webhook_events_merchant_id", "webhook_events", ["merchant_id"])
    op.create_index("ix_webhook_events_client_id", "webhook_events", ["client_id"])
    op.create_index("ix_webhook_events_phone_number_id", "webhook_events", ["phone_number_id"])
    op.create_index("ix_webhook_provider_client", "webhook_events", ["provider", "client_id"])

    # ── 16. deepseek_settings ──────────────────────────────────────────────────
    op.create_table(
        "deepseek_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("temperature", sa.Numeric(2, 1), nullable=False, server_default="0.5"),
        sa.Column("extra_system_prompt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("client_id", name="uq_deepseek_setting_per_client"),
    )
    op.create_index("ix_deepseek_settings_id", "deepseek_settings", ["id"])
    op.create_index("ix_deepseek_settings_client_id", "deepseek_settings", ["client_id"])

    # ── 17. flutterwave_subaccounts ────────────────────────────────────────────
    op.create_table(
        "flutterwave_subaccounts",
        sa.Column("client_id", sa.String(6), sa.ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("merchant_id", sa.String(6), sa.ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subaccount_id", sa.String(100), nullable=False),
        sa.Column("account_bank", sa.String(10), nullable=False),
        sa.Column("account_number", sa.String(20), nullable=False),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("split_value", sa.String(10), nullable=True),
        sa.Column("split_type", sa.String(20), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("subaccount_id", name="uq_flutterwave_subaccount_id"),
    )
    op.create_index("ix_flutterwave_subaccounts_client_id", "flutterwave_subaccounts", ["client_id"])
    op.create_index("ix_flutterwave_subaccounts_merchant_id", "flutterwave_subaccounts", ["merchant_id"])


def downgrade() -> None:
    # Drop in reverse FK order
    op.drop_table("flutterwave_subaccounts")
    op.drop_table("deepseek_settings")
    op.drop_table("webhook_events")
    op.drop_table("human_agent_tasks")
    op.drop_table("clarifications")
    op.drop_table("payments")
    op.drop_table("orders")
    op.drop_table("cart_items")
    op.drop_table("inventories")
    op.drop_table("carts")
    op.drop_table("products")
    op.drop_table("client_whatsapp_credentials")
    op.drop_table("whatsapp_message_logs")
    op.drop_table("idempotency_keys")
    op.drop_table("customer_profiles")
    op.drop_table("clients")
    op.drop_table("merchants")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS payment_status_enum")
    op.execute("DROP TYPE IF EXISTS deliverytype")
    op.execute("DROP TYPE IF EXISTS order_status")
    op.execute("DROP TYPE IF EXISTS whatsapp_message_direction")
