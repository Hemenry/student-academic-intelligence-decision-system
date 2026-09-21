"""模型基类与通用字段约定。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class TimestampMixin:
    """统一审计字段：创建时间 / 更新时间，交给数据库函数生成，避免时区漂移。"""

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PKMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
