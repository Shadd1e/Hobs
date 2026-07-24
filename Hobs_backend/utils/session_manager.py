class SessionManager:
    _sessions = {}

    @classmethod
    def get_session(cls, merchant_id: str, customer_number: str):
        key = f"{merchant_id}:{customer_number}"
        if key not in cls._sessions:
            cls._sessions[key] = {"cart": []}
        return cls._sessions[key]

    @classmethod
    def clear_session(cls, merchant_id: str, customer_number: str):
        key = f"{merchant_id}:{customer_number}"
        if key in cls._sessions:
            del cls._sessions[key]
