"""统一业务异常与全局异常处理器：让前端拿到的永远是结构一致的 JSON。"""
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class BizError(Exception):
    """业务异常基类。code 用业务错误码，便于前端做精细化提示。"""

    def __init__(self, message: str, code: str = "BIZ_ERROR", http_status: int = status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.code = code
        self.http_status = http_status
        super().__init__(message)


class AuthError(BizError):
    def __init__(self, message: str = "身份认证失败", code: str = "AUTH_FAILED"):
        super().__init__(message, code, status.HTTP_401_UNAUTHORIZED)


class PermissionError_(BizError):
    def __init__(self, message: str = "无权访问该资源", code: str = "PERMISSION_DENIED"):
        super().__init__(message, code, status.HTTP_403_FORBIDDEN)


class NotFoundError(BizError):
    def __init__(self, message: str = "资源不存在", code: str = "NOT_FOUND"):
        super().__init__(message, code, status.HTTP_404_NOT_FOUND)


class ConflictError(BizError):
    """并发/唯一约束类冲突，例如选课满员、重复选课。"""

    def __init__(self, message: str = "资源冲突", code: str = "CONFLICT"):
        super().__init__(message, code, status.HTTP_409_CONFLICT)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _biz_handler(request: Request, exc: BizError):
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(i) for i in first.get("loc", []) if i != "body")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "VALIDATION_ERROR",
                "message": f"参数校验失败：{loc} {first.get('msg', '')}".strip(),
                "data": None,
            },
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_handler(request: Request, exc: IntegrityError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "DB_INTEGRITY_ERROR", "message": "数据唯一性或外键约束冲突", "data": None},
        )

    @app.exception_handler(SQLAlchemyError)
    async def _sqlalchemy_handler(request: Request, exc: SQLAlchemyError):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": "DB_ERROR", "message": "数据库操作失败，请稍后重试", "data": None},
        )

    @app.exception_handler(Exception)
    async def _unknown_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": "INTERNAL_ERROR", "message": f"服务器内部错误：{exc}", "data": None},
        )
