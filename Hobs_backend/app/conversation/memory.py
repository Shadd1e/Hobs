# app/conversation/memory.py

from typing import Dict, Any, Optional
from app.core.redis_client import (
    _hash_phone,
    get_session,
    set_session,
    delete_session,
    delete_history,
    add_to_history,
    SESSION_TTL,
)


class ConversationMemory:
    """
    Async Redis-backed conversation memory.
    Uses full-session writes (no atomic field ops).

    Keyed by (client_id, user_phone) — not merchant_id — so that a merchant
    with multiple stores has fully isolated sessions per store.
    """

    def __init__(self, client_id: str, user_id: str):
        self.client_id = client_id
        self.user_id   = user_id
        self.session: Dict[str, Any] = {}

    @classmethod
    async def load(cls, client_id: str, user_id: str):
        self = cls(client_id, user_id)
        self.session = await get_session(client_id, user_id)
        return self

    async def _save(self):
        await set_session(self.client_id, self.user_id, self.session)

    async def get_mode(self) -> str:
        return self.session.get("mode", "idle")

    async def set_mode(self, mode: str):
        self.session["mode"] = mode
        await self._save()

    async def get(self, key: str, default=None):
        return self.session.get(key, default)

    async def set(self, key: str, value):
        self.session[key] = value
        await self._save()

    async def delete(self, key: str):
        self.session.pop(key, None)
        await self._save()

    async def update(self, updates: Dict[str, Any]):
        self.session.update(updates)
        await self._save()

    async def patch(self, updates: Dict[str, Any]):
        """
        Atomic read-modify-write using a Redis Lua script.
        Key uses _hash_phone to prevent PII exposure in Redis key listings.
        """
        from app.core.redis_client import get_session as _get_session, redis_service
        import json as _json

        key          = f"session:flow:{self.client_id}:{_hash_phone(self.user_id)}"
        updates_json = _json.dumps(updates)

        lua = """
        local raw = redis.call('GET', KEYS[1])
        local data = {}
        if raw then
            data = cjson.decode(raw)
        end
        local patch = cjson.decode(ARGV[1])
        for k, v in pairs(patch) do
            data[k] = v
        end
        local ttl = tonumber(ARGV[2])
        redis.call('SETEX', KEYS[1], ttl, cjson.encode(data))
        return cjson.encode(data)
        """

        try:
            client = await redis_service.get_client()
            result = await client.eval(lua, 1, key, updates_json, SESSION_TTL)
            self.session = _json.loads(result)
        except Exception:
            fresh = await _get_session(self.client_id, self.user_id)
            fresh.update(updates)
            self.session = fresh
            await self._save()

    async def get_choices(self):
        return self.session.get("pending_choices", [])

    async def set_choices(self, choices):
        self.session["pending_choices"] = choices or []
        await self._save()

    async def clear_choices(self):
        self.session.pop("pending_choices", None)
        await self._save()

    async def get_temp_data(self, key: str, default=None):
        return self.session.get("temp", {}).get(key, default)

    async def set_temp_data(self, key: str, value: Any):
        temp = self.session.get("temp", {})
        temp[key] = value
        self.session["temp"] = temp
        await self._save()

    async def clear_temp(self):
        self.session.pop("temp", None)
        await self._save()

    # FIX: seen_intent() removed.
    # It stored last_intent as a side effect but returned a boolean dedup signal
    # that was never checked anywhere in the codebase — a dormant footgun that
    # could silently block valid repeated intents (e.g. "add_to_cart" twice)
    # if anyone wired it up. last_intent is now written directly in
    # whatsapp_handler.py via memory.set("last_intent", intent), which is
    # clearer and does not carry an accidental dedup contract.

    async def get_customer_name(self) -> Optional[str]:
        return self.session.get("customer_name")

    async def set_customer_name(self, name: str):
        self.session["customer_name"] = name
        await self._save()

    async def get_last_search(self) -> Optional[str]:
        return self.session.get("last_search")

    async def set_last_search(self, query: str):
        self.session["last_search"] = query
        await self._save()

    async def add_user(self, text: str):
        await add_to_history(
            client_id=self.client_id,
            user_id=self.user_id,
            role="user",
            content=text,
        )

    async def add_assistant(self, text: str):
        await add_to_history(
            client_id=self.client_id,
            user_id=self.user_id,
            role="assistant",
            content=text,
        )

    async def clear(self):
        await delete_session(self.client_id, self.user_id)
        await delete_history(self.client_id, self.user_id)
        self.session = {}