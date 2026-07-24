# app/conversation/name_parser.py
"""
Single source of truth for customer name cleaning.
Used by webhook.py (awaiting_name mode) and whatsapp_handler.py
(DeepSeek customer_name extraction). Previously duplicated in both files.
"""

_PREFIXES = (
    "call me ",
    "my name is ",
    "i am ",
    "i'm ",
    "it's ",
    "they call me ",
    "just call me ",
    "name is ",
)


def parse_customer_name(raw: str) -> str:
    """
    Strip filler phrases, truncate long inputs to first word,
    and capitalise the result.

    Returns an empty string if the input is blank after cleaning
    so callers can decide whether to persist or ignore it.
    """
    name = raw.strip()[:100]
    name_lower = name.lower()

    for prefix in _PREFIXES:
        if name_lower.startswith(prefix):
            name = name[len(prefix):].strip()
            break

    words = name.split()
    if len(words) > 2:
        name = words[0]
    elif len(words) == 2:
        pass  # keep both e.g. "John Paul"

    name = name.rstrip(".,!?").strip()

    if name:
        name = name[0].upper() + name[1:]

    return name
