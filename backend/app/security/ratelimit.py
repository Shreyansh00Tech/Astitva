"""Distributed Token Bucket rate limiter backed by Redis (atomic Lua script)."""
import time
from dataclasses import dataclass

import redis

from app.core.config import get_settings

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then tokens = capacity; ts = now end
local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * refill)
local allowed = 0
local retry_after = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry_after = (cost - tokens) / refill
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(capacity / refill) + 60)
return {allowed, tostring(tokens), tostring(retry_after)}
"""

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def set_redis(client: redis.Redis) -> None:
    """Used by tests to inject a fake Redis."""
    global _client
    _client = client


@dataclass
class BucketResult:
    allowed: bool
    remaining: float
    retry_after: float


def take(bucket: str, capacity: int, refill_per_sec: float, cost: int = 1) -> BucketResult:
    r = get_redis()
    allowed, remaining, retry = r.eval(
        TOKEN_BUCKET_LUA, 1, f"astitva:tb:{bucket}", capacity, refill_per_sec, time.time(), cost
    )
    return BucketResult(bool(int(allowed)), float(remaining), float(retry))


def check_login_buckets(ip: str, email: str) -> BucketResult:
    s = get_settings()
    ip_res = take(f"login:ip:{ip}", s.ip_bucket_capacity, s.ip_bucket_refill_per_sec)
    if not ip_res.allowed:
        return ip_res
    return take(f"login:acct:{email.lower()}", s.account_bucket_capacity, s.account_bucket_refill_per_sec)


def track_distinct_accounts(ip: str, email: str, window: int = 900) -> int:
    """Credential stuffing signal: how many distinct accounts failed from this IP in the window."""
    r = get_redis()
    key = f"astitva:stuffing:{ip}"
    now = time.time()
    pipe = r.pipeline()
    pipe.zadd(key, {email.lower(): now})
    pipe.zremrangebyscore(key, 0, now - window)
    pipe.zcard(key)
    pipe.expire(key, window)
    return int(pipe.execute()[2])
