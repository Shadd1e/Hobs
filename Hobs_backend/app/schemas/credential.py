from pydantic import BaseModel, ConfigDict, StringConstraints, constr, field_validator, model_validator
from typing import Optional, Annotated
import logging
logger = logging.getLogger(__name__)

# Credential ID format: CR1234 (2 letters + 4 digits)
CredentialID = Annotated[str, StringConstraints(pattern=r'^[A-Z]{2}\d{4}$')]

class CredentialBase(BaseModel):
    id: CredentialID
    whatsapp_number: str
    token: str
    phone_id: str
    active: bool
    client_id: str

# For creating a credential
class CredentialCreate(CredentialBase):
    pass

# For reading/response
class CredentialResponse(CredentialBase):
    pass