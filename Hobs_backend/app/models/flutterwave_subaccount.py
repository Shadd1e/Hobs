# app/models/flutterwave_subaccount.py
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import relationship
from app.db.base import Base



class FlutterwaveSubaccount(Base):
    """
    One subaccount per Client (store).
    Stores the Flutterwave subaccount_id so that payments
    route directly to each store's bank account.

    Onboarding flow:
    1. Merchant provides bank details via API
    2. System calls Flutterwave POST /subaccounts
    3. Flutterwave returns subaccount_id (e.g. RS_xxxxxxxx)
    4. We store it here
    5. Checkout passes subaccount_id in every payment payload
    """

    __tablename__ = "flutterwave_subaccounts"

    client_id = Column(
        String(20),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    merchant_id = Column(
        String(20),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Flutterwave's subaccount identifier (e.g. RS_xxxxxxxxxxxxxxxx)
    subaccount_id = Column(String(100), nullable=False, unique=True)

    # Bank details (stored for reference / re-registration)
    account_bank = Column(String(10), nullable=False)       # e.g. "044" (Access Bank)
    account_number = Column(String(20), nullable=False)
    business_name = Column(String(255), nullable=False)

    # Optional: platform fee split percentage (0.0 - 100.0)
    # If set, this % goes to the platform on every transaction
    split_value = Column(String(10), nullable=True)         # stored as string e.g. "2.5"
    split_type = Column(String(20), nullable=True)          # "percentage" or "flat"

    active = Column(Boolean, default=True, nullable=False)

    provider = Column(String(20), nullable=True, default="paystack")

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    client = relationship(
        "Client",
        back_populates="flutterwave_subaccount",
        uselist=False,
    )

    def __repr__(self):
        return f"<FlutterwaveSubaccount client={self.client_id} subaccount_id={self.subaccount_id}>"
