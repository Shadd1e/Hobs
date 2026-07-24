from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.domains.tenant.models import Client
from app.domains.tenant.models import ClientWhatsAppCredential
from app.schemas.client_schema import ClientCreate, ClientUpdate
import logging

logger = logging.getLogger(__name__)


class ClientService:
    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # -----------------------------
    # CREATE
    # -----------------------------
    async def create(self, data: ClientCreate) -> Optional[Client]:
        """Create a new client"""
        # Prevent duplicate client per merchant
        result = await self.db.execute(
            select(Client).where(
                and_(
                    Client.id == data.id,
                    Client.merchant_id == data.merchant_id,
                )
            )
        )
        if result.scalars().first():
            return None

        client = Client(
            id=data.id,
            name=data.name,
            whatsapp_number=data.whatsapp_number,
            store_contact_number=data.store_contact_number,
            merchant_id=data.merchant_id,
        )

        self.db.add(client)
        await self.db.commit()
        await self.db.refresh(client)
        return client

    # -----------------------------
    # GET (merchant-scoped)
    # -----------------------------
    async def get(
        self,
        client_id: str,
        merchant_id: Optional[str] = None,
        include_credential: bool = True
    ) -> Optional[Client]:
        """Get client by ID, optionally including credential"""
        stmt = select(Client).where(Client.id == client_id)
        
        if include_credential:
            stmt = stmt.options(selectinload(Client.whatsapp_credential))
        
        if merchant_id:
            stmt = stmt.where(Client.merchant_id == merchant_id)

        result = await self.db.execute(stmt)
        return result.scalars().first()

    # -----------------------------
    # LIST (merchant-scoped)
    # -----------------------------
    async def list_all(
        self, 
        merchant_id: str,
        skip: int = 0,
        limit: int = 100,
        has_credential: Optional[bool] = None
    ) -> List[Client]:
        """List clients with optional filters"""
        stmt = select(Client).where(Client.merchant_id == merchant_id)
        
        # Eager load credential for all clients
        stmt = stmt.options(selectinload(Client.whatsapp_credential))
        
        # Apply credential filter if specified
        if has_credential is not None:
            if has_credential:
                stmt = stmt.where(Client.whatsapp_credential != None)
            else:
                stmt = stmt.where(Client.whatsapp_credential == None)
        
        # Apply pagination
        stmt = stmt.offset(skip).limit(limit).order_by(Client.created_at.desc())
        
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # -----------------------------
    # UPDATE
    # -----------------------------
    async def update(
        self,
        client_id: str,
        payload: ClientUpdate,
        merchant_id: Optional[str] = None,
    ) -> Optional[Client]:
        """Update client information"""
        client = await self.get(client_id, merchant_id, include_credential=False)
        if not client:
            return None

        # Convert payload to dict and remove protected fields
        update_data = payload.model_dump(exclude_unset=True)
        update_data.pop("merchant_id", None)
        update_data.pop("id", None)

        # Update fields
        for key, value in update_data.items():
            if value is not None:  # Only update if value is provided
                setattr(client, key, value)

        await self.db.commit()
        await self.db.refresh(client)
        return client

    # -----------------------------
    # DELETE
    # -----------------------------
    async def delete(
        self,
        client_id: str,
        merchant_id: Optional[str] = None,
    ) -> bool:
        """Delete a client (cascades to credential)"""
        client = await self.get(client_id, merchant_id, include_credential=False)
        if not client:
            return False

        await self.db.delete(client)
        await self.db.commit()
        return True

    # -----------------------------
    # CREDENTIAL MANAGEMENT (1:1)
    # -----------------------------
    
    async def get_credential(
        self,
        client_id: str,
        merchant_id: Optional[str] = None,
    ) -> Optional[ClientWhatsAppCredential]:
        """Get WhatsApp credential for a client"""
        # First verify client belongs to merchant
        client = await self.get(client_id, merchant_id, include_credential=True)
        if not client:
            return None
        
        return client.whatsapp_credential

    async def create_credential(
        self,
        client_id: str,
        credential_data: dict,
        merchant_id: Optional[str] = None,
    ) -> Optional[ClientWhatsAppCredential]:
        """Create WhatsApp credential for a client"""
        # Verify client exists and belongs to merchant
        client = await self.get(client_id, merchant_id, include_credential=True)
        if not client:
            return None
        
        # Check if client already has a credential (1:1)
        if client.whatsapp_credential:
            logger.warning(f"Client {client_id} already has a WhatsApp credential")
            return None
        
        # Check for duplicate phone_number_id
        existing_phone = await self.db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.phone_number_id == credential_data.get("phone_number_id")
            )
        )
        if existing_phone.scalars().first():
            logger.warning(f"Duplicate phone_number_id: {credential_data.get('phone_number_id')}")
            return None
        
        # Check for duplicate whatsapp_number if provided
        whatsapp_number = credential_data.get("whatsapp_number")
        if whatsapp_number:
            existing_whatsapp = await self.db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.whatsapp_number == whatsapp_number
                )
            )
            if existing_whatsapp.scalars().first():
                logger.warning(f"Duplicate whatsapp_number: {whatsapp_number}")
                return None
        
        # Create credential
        credential = ClientWhatsAppCredential(
            client_id=client_id,
            **credential_data
        )
        
        self.db.add(credential)
        await self.db.commit()
        await self.db.refresh(credential)
        return credential

    async def update_credential(
        self,
        client_id: str,
        credential_data: dict,
        merchant_id: Optional[str] = None,
    ) -> Optional[ClientWhatsAppCredential]:
        """Update WhatsApp credential for a client"""
        # Get client with credential
        client = await self.get(client_id, merchant_id, include_credential=True)
        if not client or not client.whatsapp_credential:
            return None
        
        credential = client.whatsapp_credential
        
        # Check for duplicate phone_number_id if updating
        new_phone_id = credential_data.get("phone_number_id")
        if new_phone_id and new_phone_id != credential.phone_number_id:
            existing = await self.db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.phone_number_id == new_phone_id,
                    ClientWhatsAppCredential.client_id != client_id
                )
            )
            if existing.scalars().first():
                logger.warning(f"Duplicate phone_number_id: {new_phone_id}")
                return None
        
        # Check for duplicate whatsapp_number if updating
        new_whatsapp = credential_data.get("whatsapp_number")
        if new_whatsapp and new_whatsapp != credential.whatsapp_number:
            existing = await self.db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.whatsapp_number == new_whatsapp,
                    ClientWhatsAppCredential.client_id != client_id
                )
            )
            if existing.scalars().first():
                logger.warning(f"Duplicate whatsapp_number: {new_whatsapp}")
                return None
        
        # Update fields
        for key, value in credential_data.items():
            if value is not None:  # Only update if value is provided
                setattr(credential, key, value)
        
        await self.db.commit()
        await self.db.refresh(credential)
        return credential

    async def delete_credential(
        self,
        client_id: str,
        merchant_id: Optional[str] = None,
    ) -> bool:
        """Delete WhatsApp credential for a client"""
        client = await self.get(client_id, merchant_id, include_credential=True)
        if not client or not client.whatsapp_credential:
            return False
        
        await self.db.delete(client.whatsapp_credential)
        await self.db.commit()
        return True

    # -----------------------------
    # HELPER METHODS
    # -----------------------------
    
    async def has_active_credential(
        self,
        client_id: str,
        merchant_id: Optional[str] = None,
    ) -> bool:
        """Check if client has an active WhatsApp credential"""
        credential = await self.get_credential(client_id, merchant_id)
        return bool(credential and credential.active)

    async def count_clients_with_credentials(
        self,
        merchant_id: str,
    ) -> int:
        """Count how many clients have WhatsApp credentials"""
        result = await self.db.execute(
            select(Client)
            .join(ClientWhatsAppCredential, Client.id == ClientWhatsAppCredential.client_id)
            .where(Client.merchant_id == merchant_id)
            .where(ClientWhatsAppCredential.active == True)
        )
        return len(result.scalars().all())