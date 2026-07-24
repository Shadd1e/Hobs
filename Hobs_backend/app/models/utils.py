from uuid import uuid4
import logging
logger = logging.getLogger(__name__)

def generate_uuid() -> str:
    return str(uuid4())