"""Redis 客户端封装。

用途（也是面试里能展开讲的三点）：
1. token 黑名单：登出/改密后立即失效，解决 JWT 无状态无法主动退出的问题；
2. 选课分布式锁：多实例部署时先用 Redis 锁做粗粒度互斥，再进 MySQL 行锁做精确扣减；
3. 热点缓存：开课计划列表、推荐结果、统计看板等读多写少数据缓存，降低 DB 压力。

Redis 不可用时降级为"无缓存直连 DB"，保证核心业务不被中间件拖垮（fail-open）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool = redis.ConnectionPool(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    password=settings.REDIS_PASSWORD or None,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
    health_check_interval=30,
)

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(connection_pool=_pool)
    return _client


def redis_available() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:  # pragma: no cover - 中间件不可用时走降级分支
        return False


# --------------------------------------------------------------------------
# 缓存
# --------------------------------------------------------------------------
def cache_get(key: str) -> Any | None:
    try:
        raw = get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    try:
        get_redis().setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
    except Exception as exc:  # pragma: no cover
        logger.warning("缓存写入失败，降级直连数据库: %s", exc)


def cache_delete_prefix(prefix: str) -> None:
    try:
        client = get_redis()
        for key in client.scan_iter(match=f"{prefix}*", count=200):
            client.delete(key)
    except Exception:  # pragma: no cover
        pass


# --------------------------------------------------------------------------
# token 黑名单
# --------------------------------------------------------------------------
def blacklist_token(jti: str, ttl: int) -> None:
    try:
        get_redis().setex(f"token:blacklist:{jti}", max(ttl, 1), "1")
    except Exception as exc:  # pragma: no cover
        logger.warning("token 黑名单写入失败: %s", exc)


def is_token_blacklisted(jti: str) -> bool:
    try:
        return bool(get_redis().exists(f"token:blacklist:{jti}"))
    except Exception:  # pragma: no cover
        return False


# --------------------------------------------------------------------------
# 分布式锁
# --------------------------------------------------------------------------
class RedisLock:
    """基于 SET NX PX + Lua 校验持有者的可重入安全锁。"""

    _RELEASE_LUA = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    else
        return 0
    end
    """

    def __init__(self, key: str, timeout: int = 5, wait: float = 2.0):
        self.key = f"lock:{key}"
        self.timeout = timeout
        self.wait = wait
        self.token = uuid.uuid4().hex
        self.acquired = False

    def __enter__(self) -> "RedisLock":
        client = get_redis()
        deadline = time.time() + self.wait
        try:
            while time.time() < deadline:
                if client.set(self.key, self.token, nx=True, px=self.timeout * 1000):
                    self.acquired = True
                    return self
                time.sleep(0.05)
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis 锁不可用，降级为 MySQL 行锁保障: %s", exc)
        return self

    def __exit__(self, *exc_info) -> None:
        if not self.acquired:
            return
        try:
            get_redis().eval(self._RELEASE_LUA, 1, self.key, self.token)
        except Exception:  # pragma: no cover
            pass
        self.acquired = False
