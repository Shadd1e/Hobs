"""admin action audit log (append-only) + verification review columns

Revision ID: 0023_admin_audit_log
Revises: 0022_verification_grace_period
Create Date: 2026-08-04

admin_action_logs is protected at the database level: a BEFORE UPDATE OR
DELETE trigger raises an exception unconditionally. This holds no matter
what role or admin level is calling — the application itself has no code
path that could remove or edit a row even if it tried to. The only way to
alter this table is a manual DBA operation outside the app (e.g. dropping
the trigger first), which is itself the kind of action that should leave
its own trail elsewhere.

Also adds verification_reviewed_at / verification_review_outcome to
merchant_applications — every submitted CAC/BVN/NIN goes to manual review
(verification_status stays "pending_manual_review" until an admin acts on
it via POST /admin/whatsapp-setup/applications/{id}/verification/approve
or /reject). These columns record that an admin actually looked at it,
separately from application-level approval/rejection (reviewed_at above).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = "0023_admin_audit_log"
down_revision = "0022_verification_grace_period"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "admin_action_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_session_id", sa.String(16), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_action_logs_action", "admin_action_logs", ["action"])
    op.create_index("ix_admin_action_logs_target_id", "admin_action_logs", ["target_id"])
    op.create_index("ix_admin_action_logs_created_at", "admin_action_logs", ["created_at"])

    # ── DB-level append-only enforcement ─────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION admin_action_logs_block_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'admin_action_logs is append-only: % is not permitted on this table (row id: %)',
                TG_OP, OLD.id;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_action_logs_no_update
        BEFORE UPDATE ON admin_action_logs
        FOR EACH ROW EXECUTE FUNCTION admin_action_logs_block_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_action_logs_no_delete
        BEFORE DELETE ON admin_action_logs
        FOR EACH ROW EXECUTE FUNCTION admin_action_logs_block_mutation();
        """
    )

    # ── verification review tracking ─────────────────────────────────────
    op.add_column(
        "merchant_applications",
        sa.Column(
            "verification_reviewed_at", sa.DateTime(timezone=True), nullable=True,
            comment="When an admin actually reviewed a submitted CAC/BVN/NIN.",
        ),
    )
    op.add_column(
        "merchant_applications",
        sa.Column(
            "verification_review_outcome", sa.String(20), nullable=True,
            comment="verified | rejected — set alongside verification_reviewed_at.",
        ),
    )
    op.add_column(
        "merchant_applications",
        sa.Column(
            "last_admin_review_nudge_at", sa.DateTime(timezone=True), nullable=True,
            comment="De-dupe guard for the admin-facing 'you have a pending verification "
                    "review' nudge (Slack + WhatsApp). See admin_review_nudge_job.py.",
        ),
    )


def downgrade() -> None:
    op.drop_column("merchant_applications", "last_admin_review_nudge_at")
    op.drop_column("merchant_applications", "verification_review_outcome")
    op.drop_column("merchant_applications", "verification_reviewed_at")

    op.execute("DROP TRIGGER IF EXISTS admin_action_logs_no_delete ON admin_action_logs;")
    op.execute("DROP TRIGGER IF EXISTS admin_action_logs_no_update ON admin_action_logs;")
    op.execute("DROP FUNCTION IF EXISTS admin_action_logs_block_mutation();")

    op.drop_index("ix_admin_action_logs_created_at", table_name="admin_action_logs")
    op.drop_index("ix_admin_action_logs_target_id", table_name="admin_action_logs")
    op.drop_index("ix_admin_action_logs_action", table_name="admin_action_logs")
    op.drop_table("admin_action_logs")
