"""安全组件：密码哈希（bcrypt）+ JWT 签发/校验。

设计说明：
- 密码用 bcrypt 加盐哈希，数据库里永远不存明文；
- Token 使用 JWT（HS256），payload 里带 sub(用户ID)、role(角色)、jti(唯一ID)，
  jti 的作用是支持"登出即失效"——把 jti 写入 Redis 黑名单，鉴权时先查黑名单。
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = settings.JWT_ALGORITHM


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: int, username: str, role: str, jti: str) -> tuple[str, int]:
    """返回 (token, 过期秒数)，过期秒数交给前端做无感刷新倒计时。"""
    expire_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expire_seconds)).timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)
    return token, expire_seconds


def decode_access_token(token: str) -> dict[str, Any]:
    """解析 token，失败时抛 jwt 异常，由上层转成 401。"""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
