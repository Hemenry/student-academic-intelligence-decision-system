"""SQLAlchemy 引擎 / Session 管理。

要点：
- QueuePool + pool_pre_ping + pool_recycle：解决 MySQL 侧 wait_timeout 导致的
  "MySQL server has gone away"（长连接失效）；
- expire_on_commit=False：commit 之后对象属性仍可读，避免序列化时报 DetachedInstanceError；
- get_db 依赖用 yield，请求结束自动关闭，异常时回滚。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    echo=settings.DB_ECHO,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
