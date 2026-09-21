"""FastAPI 依赖注入：统一鉴权与角色校验。

用法：
    @router.get("/admin-only")
    def x(user: SysUser = Depends(require_admin)): ...

数据权限的核心思路：**角色决定能看什么**。
- 学生接口一律不接受前端传 student_id，只从 token 里取当前登录学生的档案，
  从根上杜绝"改个 id 就能看别人成绩"的越权问题（IDOR）。
- 管理员接口通过 require_admin 拦截，教师用 require_teacher_or_admin。
"""
from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AuthError, PermissionError_
from app.core.redis_client import is_token_blacklisted
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import UserRole, UserStatus
from app.models.user import Student, SysUser, Teacher

DbSession = Annotated[Session, Depends(get_db)]


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("缺少访问令牌，请先登录")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> SysUser:
    token = _extract_token(authorization)
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("登录已过期，请重新登录", code="TOKEN_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("访问令牌无效") from exc

    # 黑名单校验：登出/改密后 token 立即失效
    if is_token_blacklisted(payload.get("jti", "")):
        raise AuthError("该登录凭证已失效，请重新登录", code="TOKEN_REVOKED")

    user = db.get(SysUser, int(payload["sub"]))
    if user is None:
        raise AuthError("用户不存在")
    if user.status != UserStatus.ACTIVE:
        raise AuthError("账号已被禁用，请联系教务管理员", code="ACCOUNT_DISABLED")
    return user


CurrentUser = Annotated[SysUser, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> SysUser:
    if user.role != UserRole.ADMIN:
        raise PermissionError_("该操作仅限教务管理员")
    return user


def require_teacher_or_admin(user: CurrentUser) -> SysUser:
    if user.role not in (UserRole.ADMIN, UserRole.TEACHER):
        raise PermissionError_("该操作仅限教师或教务管理员")
    return user


AdminUser = Annotated[SysUser, Depends(require_admin)]
TeacherUser = Annotated[SysUser, Depends(require_teacher_or_admin)]


def get_current_student(db: DbSession, user: CurrentUser) -> Student:
    """取当前登录用户的学生档案；非学生角色直接拒绝。"""
    if user.role != UserRole.STUDENT:
        raise PermissionError_("该接口仅供学生使用")
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        raise AuthError("学生档案不存在，请联系教务管理员", code="PROFILE_MISSING")
    return student


CurrentStudent = Annotated[Student, Depends(get_current_student)]


def get_current_teacher(db: DbSession, user: CurrentUser) -> Teacher:
    if user.role not in (UserRole.TEACHER, UserRole.ADMIN):
        raise PermissionError_("该接口仅供教师使用")
    teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
    if teacher is None:
        raise AuthError("教师档案不存在", code="PROFILE_MISSING")
    return teacher


CurrentTeacher = Annotated[Teacher, Depends(get_current_teacher)]
