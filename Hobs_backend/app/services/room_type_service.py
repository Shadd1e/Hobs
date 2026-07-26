# app/services/room_type_service.py
import logging
logger = logging.getLogger(__name__)

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError

from app.models.room_type import RoomType
from app.schemas.room_type import RoomTypeCreate


class RoomTypeService:
    """
    Async CRUD service for RoomType. Direct port of ProductService's pattern
    minus the auto-inventory step (rooms are individually created via
    RoomService, not an auto-generated stock count).

    Price is the one field hotel admins will touch most — same "manually
    adjust price, no seasonal logic yet" model that store owners had for
    Product.price.
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # -----------------------------
    # CREATE
    # -----------------------------
    async def create(self, data: RoomTypeCreate) -> Optional[RoomType]:
        if not data.merchant_id or not data.client_id:
            return None

        stmt = select(RoomType).where(
            and_(
                RoomType.name == data.name,
                RoomType.merchant_id == data.merchant_id,
                RoomType.client_id == data.client_id,
            )
        )
        existing = await self.db.execute(stmt)
        if existing.scalars().first():
            return None

        room_type = RoomType(
            name=data.name,
            description=data.description,
            price=data.price,
            image_url=data.image_url,
            merchant_id=data.merchant_id,
            client_id=data.client_id,
        )

        try:
            self.db.add(room_type)
            await self.db.commit()
            await self.db.refresh(room_type)
            return room_type
        except IntegrityError:
            await self.db.rollback()
            return None

    # -----------------------------
    # READ
    # -----------------------------
    async def get(
        self,
        room_type_id,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Optional[RoomType]:
        stmt = select(RoomType).where(RoomType.id == room_type_id)
        if merchant_id:
            stmt = stmt.where(RoomType.merchant_id == merchant_id)
        if client_id:
            stmt = stmt.where(RoomType.client_id == client_id)

        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_all(
        self,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> List[RoomType]:
        stmt = select(RoomType)
        if merchant_id:
            stmt = stmt.where(RoomType.merchant_id == merchant_id)
        if client_id:
            stmt = stmt.where(RoomType.client_id == client_id)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    # -----------------------------
    # UPDATE — this is the "admin adjusts price" endpoint
    # -----------------------------
    async def update(
        self,
        room_type_id,
        payload: dict,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Optional[RoomType]:
        room_type = await self.get(room_type_id, merchant_id, client_id)
        if not room_type:
            return None

        payload.pop("merchant_id", None)
        payload.pop("client_id", None)

        for key, value in payload.items():
            if value is not None:
                setattr(room_type, key, value)

        await self.db.commit()
        await self.db.refresh(room_type)
        return room_type

    # -----------------------------
    # DELETE
    # -----------------------------
    async def delete(
        self,
        room_type_id,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> bool:
        room_type = await self.get(room_type_id, merchant_id, client_id)
        if not room_type:
            return False

        # Room.room_type_id is a RESTRICT FK — this will raise IntegrityError
        # at flush time if rooms still reference this type. Caught here so
        # the API returns a clean error instead of a raw DB exception.
        try:
            await self.db.delete(room_type)
            await self.db.commit()
            return True
        except IntegrityError:
            await self.db.rollback()
            raise ValueError(
                "Cannot delete a room type that still has rooms assigned to it. "
                "Reassign or delete those rooms first."
            )
