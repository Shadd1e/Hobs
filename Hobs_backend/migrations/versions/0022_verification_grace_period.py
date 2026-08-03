"""verification grace period — reminder tracking + messaging suspension

Revision ID: 0022_verification_grace_period
Revises: a8f3d21c9e04
Create Date: 2026-08-03

Supports the 7-day NIN/CAC verification grace period:

  merchant_applications:
    verification_skipped_at             — stamped when the wizard is finalised
                                           without CAC/BVN/NIN. Anchor for the
                                           day 2/4/6/7 reminder sequence.
    verification_reminder_count         — 0-5, advances through that sequence.
    last_verification_reminder_sent_at  — de-dupe guard for the reminder job.
    verification_admin_alert_sent_at    — set once the day-7 Slack + admin
                                           dashboard nudge has fired.

  merchants:
    messaging_suspended_at — non-null blocks outbound WhatsApp messaging.
    Set manually by an admin (this migration does not automate suspension —
    see app/api/v1/workers/verification_grace_job.py for why).
"""
from alembic import op
import sqlalchemy as sa

revision      = "0022_verification_grace_period"
down_revision = "a8f3d21c9e04"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        "merchant_applications",
        sa.Column(
            "verification_skipped_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set when the applicant finalises the wizard without submitting "
                    "verification. Anchor for the day 2/4/6/7 reminder sequence.",
        ),
    )
    op.add_column(
        "merchant_applications",
        sa.Column(
            "verification_reminder_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="0-5. Advances through the day2/day4/day6/day7am/day7pm sequence.",
        ),
    )
    op.add_column(
        "merchant_applications",
        sa.Column(
            "last_verification_reminder_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "merchant_applications",
        sa.Column(
            "verification_admin_alert_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set once the day-7 Slack + admin-dashboard nudge has fired for "
                    "this application, so it doesn't re-send every job run.",
        ),
    )
    op.add_column(
        "merchants",
        sa.Column(
            "messaging_suspended_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Non-null = outbound WhatsApp messaging is blocked for this merchant.",
        ),
    )


def downgrade() -> None:
    op.drop_column("merchants", "messaging_suspended_at")
    op.drop_column("merchant_applications", "verification_admin_alert_sent_at")
    op.drop_column("merchant_applications", "last_verification_reminder_sent_at")
    op.drop_column("merchant_applications", "verification_reminder_count")
    op.drop_column("merchant_applications", "verification_skipped_at")
