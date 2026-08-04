# app/models/merchant_application.py
"""
MerchantApplication — a durable record of every "Apply to Use" submission.

Previously, POST /merchants/apply only fired two emails and a Slack alert,
then discarded the submitted data entirely (see the old docstring on that
endpoint: "No database write occurs"). That meant an application existed
nowhere except a Slack message — if it scrolled past or was missed, it was
gone, and there was nothing for admin to look at on the WhatsApp-setup page.

This table fixes that: every submission is stored here with status
"pending" and stays visible in the admin dashboard until an admin approves
it (which creates the real Merchant + Client row and emails the merchant
their login details) or rejects it.
"""

from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, Numeric, func
from app.db.base import Base
from app.core.crypto import EncryptedString


class MerchantApplication(Base):
    __tablename__ = "merchant_applications"

    id = Column(String(20), primary_key=True, index=True)

    # ── Business info ──────────────────────────────────────────────────────
    # Nullable: a draft row exists after step 1 (name + contact only), before
    # business details are filled in at step 2.
    business_name = Column(String(255), nullable=True)
    business_type = Column(String(100), nullable=True)
    city_state    = Column(String(150), nullable=True)

    # ── Onboarding wizard: registration status + verification (step 2/3) ───
    registration_status = Column(
        String(20), nullable=True,
        comment="registered | unregistered — chosen in step 2.",
    )
    cac_number = Column(EncryptedString(500), nullable=True,
        comment="CAC RC/BN number, encrypted at rest. Only set for registered businesses.")
    bvn = Column(EncryptedString(500), nullable=True, comment="Encrypted at rest.")
    nin = Column(EncryptedString(500), nullable=True, comment="Encrypted at rest.")
    verification_method = Column(String(20), nullable=True, comment="cac | bvn | nin")
    verification_status = Column(
        String(30), nullable=True,
        comment="not_started | pending_manual_review | verified | failed",
    )
    verification_name_on_file = Column(
        String(255), nullable=True,
        comment="Name returned by the verification provider, checked against full_name.",
    )
    transaction_limit = Column(Numeric(12, 2), nullable=True)

    # ── Terms / indemnity acceptance (step 4) ───────────────────────────────
    # Audit trail, not just a boolean: if terms change later, this records
    # exactly which version they agreed to, when, and from what IP.
    terms_version     = Column(String(20), nullable=True)
    terms_accepted    = Column(Boolean, nullable=False, default=False)
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    terms_accepted_ip = Column(String(64), nullable=True)

    # ── Resumable wizard state ──────────────────────────────────────────────
    resume_token = Column(
        String(48), nullable=True, unique=True, index=True,
        comment="Bearer token for the 'continue your application' link. "
                "Separate from link_token (the older add-WhatsApp-later flow).",
    )
    resume_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    current_step          = Column(Integer, nullable=False, default=1)
    last_activity_at       = Column(DateTime(timezone=True), nullable=True)
    reminder_count          = Column(Integer, nullable=False, default=0)
    last_reminder_sent_at  = Column(DateTime(timezone=True), nullable=True)

    # ── Verification grace period (7-day nudge sequence) ────────────────────
    # Separate from reminder_count/last_reminder_sent_at above, which track
    # the *idle draft* reminder job (app/api/v1/workers/reminder_job.py).
    # These track a different sequence: once an applicant finishes the
    # wizard WITHOUT submitting CAC/BVN/NIN (verification_method is null),
    # verification_skipped_at is stamped and the clock starts. See
    # app/api/v1/workers/verification_grace_job.py.
    verification_skipped_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Set when the applicant finalises the wizard without submitting "
                "verification. Anchor for the day 2/4/6/7 reminder sequence.",
    )
    verification_reminder_count = Column(
        Integer, nullable=False, default=0,
        comment="0-5. Advances through the day2/day4/day6/day7am/day7pm sequence.",
    )
    last_verification_reminder_sent_at = Column(DateTime(timezone=True), nullable=True)
    verification_admin_alert_sent_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Set once the day-7 Slack + admin-dashboard nudge has fired for this "
                "application, so it doesn't get re-sent every time the job runs.",
    )

    # Every submitted CAC/BVN/NIN goes to manual review — verification_status
    # sits at "pending_manual_review" until an admin acts on it. These are
    # separate from reviewed_at (application-level approve/reject) below.
    verification_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    verification_review_outcome = Column(
        String(20), nullable=True, comment="verified | rejected",
    )
    last_admin_review_nudge_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="De-dupe guard for the admin-facing pending-review nudge "
                "(Slack + WhatsApp). See admin_review_nudge_job.py.",
    )


    # ── Applicant info ─────────────────────────────────────────────────────
    full_name       = Column(String(255), nullable=False)
    email            = Column(String(255), nullable=False, index=True)
    phone_number     = Column(String(30),  nullable=False)
    whatsapp_number  = Column(
        String(30), nullable=True,
        comment="WhatsApp number the applicant wants connected to their store. "
                "Optional at submission — may be filled in later via the link_token page.",
    )
    link_token = Column(
        String(48), nullable=True, unique=True, index=True,
        comment="Public, unguessable token for the 'add my WhatsApp number' page. "
                "Not the same as id — id is shown in Slack/admin UI, this isn't.",
    )

    # ── Operations info ────────────────────────────────────────────────────
    num_branches           = Column(Integer, nullable=False, default=1)
    monthly_order_volume   = Column(String(50),  nullable=True)
    uses_whatsapp_manual   = Column(Boolean, nullable=False, default=False)
    uses_delivery_service  = Column(Boolean, nullable=False, default=False)

    # ── Discovery & comments ───────────────────────────────────────────────
    heard_about_us = Column(String(200), nullable=True)
    comments       = Column(Text, nullable=True)

    # ── Review state ───────────────────────────────────────────────────────
    status = Column(
        String(20), nullable=False, default="pending", index=True,
        comment="draft | pending | approved | rejected | needs_attention | abandoned",
    )
    merchant_id = Column(
        String(20), nullable=True,
        comment="Set once approved — links to the Merchant row this application became.",
    )
    last_error = Column(
        Text, nullable=True,
        comment="Why the last approval attempt failed, when status='needs_attention'.",
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        comment="When the application was submitted via the public Apply form.",
    )

    def __repr__(self):
        return (
            f"<MerchantApplication(id={self.id}, business={self.business_name!r}, "
            f"status={self.status})>"
        )
