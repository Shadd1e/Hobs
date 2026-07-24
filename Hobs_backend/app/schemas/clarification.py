from typing import List
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator
import logging
logger = logging.getLogger(__name__)

class ClarificationOptionSchema(BaseModel):
    id: str
    label: str

class ClarificationRequestSchema(BaseModel):
    session_id: str
    message: str
    options: List[ClarificationOptionSchema]

class ClarificationResponseSchema(BaseModel):
    session_id: str
    selected_option: str