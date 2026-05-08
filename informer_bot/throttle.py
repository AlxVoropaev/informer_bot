"""Shared rate limiters for Telethon (MTProto) calls to prevent FloodWait."""
from aiolimiter import AsyncLimiter

# 1 req/sec — high-flood-risk MTProto methods (GetFullChannelRequest, get_entity).
expensive_limiter = AsyncLimiter(max_rate=1, time_period=1.0)

# 5 req/sec — bulk reads/downloads (iter_messages, download_media).
cheap_limiter = AsyncLimiter(max_rate=5, time_period=1.0)
