import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_
from typing import Optional

from app.db.session import get_db
from app.models.client_whatsapp_credential import ClientWhatsAppCredential
from app.models.client_model import Client
from app.schemas.client_whatsapp_credential import (
    ClientWhatsAppCredentialCreate,
    ClientWhatsAppCredentialUpdate,
    ClientWhatsAppCredentialOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/whatsapp-credentials",
    tags=["WhatsApp Credentials"],
)


@router.post(
    "/",
    response_model=ClientWhatsAppCredentialOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create WhatsApp Credential Mapping",
    description="Create a WhatsApp credential mapping for client routing (no tokens stored)"
)
async def create_credential(
    data: ClientWhatsAppCredentialCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a WhatsApp credential mapping for client routing"""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Merchant authentication required",
        )

    logger.info(f"Creating credential mapping for merchant {merchant_id}, client {data.client_id}")

    try:
        # Verify client exists and belongs to merchant
        client_res = await db.execute(
            select(Client).where(
                and_(
                    Client.id == data.client_id,
                    Client.merchant_id == merchant_id,
                )
            )
        )
        client = client_res.scalars().first()
        if not client:
            logger.error(f"Client {data.client_id} not found for merchant {merchant_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found or does not belong to merchant",
            )

        # Check if client already has a credential mapping (1:1 relationship)
        existing_cred = await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == data.client_id
            )
        )
        if existing_cred.scalars().first():
            logger.error(f"Client {data.client_id} already has a WhatsApp credential mapping")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Client already has a WhatsApp credential mapping. Use update instead.",
            )

        # Check for duplicate phone_number_id
        duplicate_phone = await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.phone_number_id == data.phone_number_id
            )
        )
        if duplicate_phone.scalars().first():
            logger.error(f"Duplicate phone_number_id: {data.phone_number_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This WhatsApp phone number ID is already registered",
            )

        # Create credential mapping (no token fields)
        cred = ClientWhatsAppCredential(**data.model_dump())
        db.add(cred)
        await db.commit()
        await db.refresh(cred)
        
        logger.info(f"Credential mapping created for client {data.client_id}")
        
        return cred
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create credential mapping: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create credential mapping"
        )


@router.get(
    "/",
    response_model=list[ClientWhatsAppCredentialOut],
    summary="List Credential Mappings",
    description="List WhatsApp credential mappings for merchant's clients"
)
async def list_credentials(
    request: Request,
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(True, description="Return only active mappings"),
    client_id: Optional[str] = Query(None, description="Filter by client ID (e.g., CL5678)"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=100, description="Pagination limit (max 100)"),
):
    """List WhatsApp credential mappings for merchant's clients"""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Merchant authentication required",
        )

    try:
        # Build base query with join to verify merchant ownership
        stmt = (
            select(ClientWhatsAppCredential)
            .join(Client, ClientWhatsAppCredential.client_id == Client.id)
            .where(Client.merchant_id == merchant_id)
        )

        # Apply filters
        if active_only:
            stmt = stmt.where(ClientWhatsAppCredential.active.is_(True))

        if client_id:
            # Verify client belongs to merchant
            client_check = await db.execute(
                select(Client).where(
                    and_(
                        Client.id == client_id,
                        Client.merchant_id == merchant_id,
                    )
                )
            )
            if not client_check.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Client does not belong to your merchant",
                )
            stmt = stmt.where(ClientWhatsAppCredential.client_id == client_id)

        # Apply pagination and ordering
        stmt = (
            stmt.order_by(ClientWhatsAppCredential.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        # Execute query
        res = await db.execute(stmt)
        creds = res.scalars().all()
        
        logger.info(f"Found {len(creds)} credential mappings for merchant {merchant_id}")

        return creds
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing credential mappings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve credential mappings"
        )


@router.get(
    "/{client_id}",
    response_model=ClientWhatsAppCredentialOut,
    summary="Get Credential Mapping by Client ID",
    description="Get credential mapping details by Client ID"
)
async def get_credential_by_client(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get credential mapping by Client ID (1:1 relationship)"""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Merchant authentication required",
        )

    try:
        # Verify client belongs to merchant
        client_res = await db.execute(
            select(Client).where(
                and_(
                    Client.id == client_id,
                    Client.merchant_id == merchant_id,
                )
            )
        )
        if not client_res.scalars().first():
            logger.warning(f"Access denied: Client {client_id} not owned by merchant {merchant_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Client does not belong to your merchant",
            )

        # Get the credential mapping
        res = await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == client_id
            )
        )
        cred = res.scalars().first()
        
        if not cred:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No WhatsApp credential mapping found for this client",
            )

        return cred
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving credential mapping for client {client_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve credential mapping"
        )


@router.put(
    "/{client_id}",
    response_model=ClientWhatsAppCredentialOut,
    summary="Update Credential Mapping by Client ID",
    description="Update credential mapping details by Client ID"
)
async def update_credential(
    client_id: str,
    data: ClientWhatsAppCredentialUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update credential mapping by Client ID"""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Merchant authentication required",
        )

    try:
        # Verify client belongs to merchant
        client_res = await db.execute(
            select(Client).where(
                and_(
                    Client.id == client_id,
                    Client.merchant_id == merchant_id,
                )
            )
        )
        if not client_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Client does not belong to your merchant",
            )

        # Get credential mapping with lock
        res = await db.execute(
            select(ClientWhatsAppCredential)
            .where(ClientWhatsAppCredential.client_id == client_id)
            .with_for_update()
        )
        cred = res.scalars().first()
        
        if not cred:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No WhatsApp credential mapping found for this client",
            )

        # Check for duplicate phone_number_id if being updated
        if data.phone_number_id and data.phone_number_id != cred.phone_number_id:
            existing = await db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.phone_number_id == data.phone_number_id,
                    ClientWhatsAppCredential.client_id != client_id
                )
            )
            if existing.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This WhatsApp phone number ID is already registered",
                )

        # Update fields
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:  # Only update if value is provided
                setattr(cred, field, value)

        await db.commit()
        await db.refresh(cred)
        
        logger.info(f"Credential mapping updated for client {client_id}")

        return cred
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update credential mapping for client {client_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update credential mapping"
        )


@router.delete(
    "/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate Credential Mapping",
    description="Deactivate a credential mapping (soft delete) by Client ID"
)
async def delete_credential(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Deactivate credential mapping by Client ID"""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Merchant authentication required",
        )

    try:
        # Verify client belongs to merchant
        client_res = await db.execute(
            select(Client).where(
                and_(
                    Client.id == client_id,
                    Client.merchant_id == merchant_id,
                )
            )
        )
        if not client_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Client does not belong to your merchant",
            )

        # Get credential mapping
        res = await db.execute(
            select(ClientWhatsAppCredential)
            .where(ClientWhatsAppCredential.client_id == client_id)
            .with_for_update()
        )
        cred = res.scalars().first()
        
        if not cred:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No WhatsApp credential mapping found for this client",
            )

        # Soft delete (deactivate)
        if cred.active:
            cred.active = False
            await db.commit()
            logger.info(f"Credential mapping deactivated for client {client_id}")
        else:
            logger.info(f"Credential mapping already inactive for client {client_id}")
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to deactivate credential mapping for client {client_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate credential mapping"
        )


@router.patch(
    "/{client_id}/reactivate",
    response_model=ClientWhatsAppCredentialOut,
    summary="Reactivate Credential Mapping",
    description="Reactivate a deactivated credential mapping by Client ID"
)
async def reactivate_credential(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reactivate credential mapping by Client ID"""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Merchant authentication required",
        )

    try:
        # Verify client belongs to merchant
        client_res = await db.execute(
            select(Client).where(
                and_(
                    Client.id == client_id,
                    Client.merchant_id == merchant_id,
                )
            )
        )
        if not client_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Client does not belong to your merchant",
            )

        # Get credential mapping
        res = await db.execute(
            select(ClientWhatsAppCredential)
            .where(ClientWhatsAppCredential.client_id == client_id)
            .with_for_update()
        )
        cred = res.scalars().first()
        
        if not cred:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No WhatsApp credential mapping found for this client",
            )

        if cred.active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Credential mapping already active",
            )

        cred.active = True
        await db.commit()
        await db.refresh(cred)
        
        logger.info(f"Credential mapping reactivated for client {client_id}")

        return cred
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to reactivate credential mapping for client {client_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reactivate credential mapping"
        )
