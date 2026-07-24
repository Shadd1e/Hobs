import logging
logger = logging.getLogger(__name__)

from pydantic import BaseModel, ConfigDict, Field
from typing import Union, Optional
import uuid


class FuzzyMatchResultSchema(BaseModel):
    """
    Schema for fuzzy match results between user query and product names.
    """

    product_id: Union[str, uuid.UUID] = Field(..., description="UUID of the matched product")
    name: str = Field(..., min_length=1, description="Product name that matched")

    # Fuzzy confidence
    score: float = Field(..., ge=0, le=100, description="Match score between 0 and 100")

    # Product details from database
    price: Optional[float] = Field(default=None, description="Product price")
    currency: Optional[str] = Field(default=None, description="Currency code (NGN, USD, etc)")
    description: Optional[str] = Field(default=None, description="Product description")
    quantity: Optional[int] = Field(default=0, description="Available inventory quantity")

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)