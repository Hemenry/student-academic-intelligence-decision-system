"""统一响应包装：{code, message, data}，前端 request 拦截器只处理这一种结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Resp(BaseModel, Generic[T]):
    code: str = "OK"
    message: str = "success"
    data: T | None = None


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {"code": "OK", "message": message, "data": data}


class PageData(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]
