import logging
logger = logging.getLogger(__name__)

# app/schemas/deepseek_setting.py
from pydantic import BaseModel, ConfigDict, StringConstraints, constr, field_validator, model_validator
from typing import Annotated, Optional
from datetime import datetime

ClientID = Annotated[str, StringConstraints(pattern=r'^ST[A-Z0-9]{6}$')]

class DeepSeekSettingBase(BaseModel):
    client_id: ClientID
    active: bool = True
    temperature: float = 0.5
    extra_system_prompt: Optional[str] = None

class DeepSeekSettingCreate(DeepSeekSettingBase):
    pass

class DeepSeekSettingRead(DeepSeekSettingBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
