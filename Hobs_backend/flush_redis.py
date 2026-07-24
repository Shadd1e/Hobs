# flush_redis.py
import redis

r = redis.from_url(
    "redis://default:hlISCPLQmBsfDrATKUbCzjaVpNVwnPJp@maglev.proxy.rlwy.net:41130",
    decode_responses=True,
)

r.flushdb()
print("Redis flushed")