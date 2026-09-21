"""认证与账号接口。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import AuthError
from app.core.redis_client import blacklist_token
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.enums import UserRole, UserStatus
from app.models.user import Student, SysUser, Teacher
from app.schemas import ChangePasswordIn, LoginIn, LoginOut, Resp, StudentBrief, TeacherBrief, UserOut

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=Resp[LoginOut], summary="登录（管理员/教师/学生统一入口）")
def login(payload: LoginIn, db: DbSession):
    """统一登录：账号不存在与密码错误返回同一提示，避免被枚举出有效账号。

    安全细节：
    - 密码用 bcrypt 校验，数据库不存明文；
    - 登录成功后写回 last_login_at，便于异常登录排查；
    - 签发的 JWT 带 jti，登出时把 jti 加入 Redis 黑名单实现"即时失效"。
    """
    user = db.execute(select(SysUser).where(SysUser.username == payload.username)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthError("账号或密码错误", code="BAD_CREDENTIALS")
    if user.status != UserStatus.ACTIVE:
        raise AuthError("账号已被禁用，请联系教务管理员", code="ACCOUNT_DISABLED")

    user.last_login_at = datetime.now()
    db.commit()

    jti = uuid.uuid4().hex
    token, expires_in = create_access_token(
        user_id=user.id, username=user.username, role=user.role.value, jti=jti
    )

    profile = None
    if user.role == UserRole.STUDENT:
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        profile = StudentBrief.model_validate(student) if student else None
    elif user.role == UserRole.TEACHER:
        teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
        profile = TeacherBrief.model_validate(teacher) if teacher else None

    return {
        "code": "OK",
        "message": "登录成功",
        "data": {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "user": UserOut.model_validate(user),
            "profile": profile,
        },
    }


@router.post("/logout", response_model=Resp[dict], summary="登出（token 立即失效）")
def logout(
    user: CurrentUser,
    authorization: Annotated[str | None, Header()] = None,
):
    """JWT 本身无状态、无法主动撤销，这里把 jti 写入 Redis 黑名单补上这个能力。"""
    token = authorization.split(" ", 1)[1] if authorization and " " in authorization else ""
    if token:
        try:
            payload = decode_access_token(token)
            ttl = max(int(payload.get("exp", 0)) - int(datetime.now().timestamp()), 1)
            blacklist_token(payload.get("jti", ""), ttl)
        except Exception:
            pass
    return {"code": "OK", "message": "已退出登录", "data": None}


@router.get("/me", response_model=Resp[dict], summary="获取当前登录用户信息")
def me(db: DbSession, user: CurrentUser):
    profile: dict | None = None
    if user.role == UserRole.STUDENT:
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student:
            profile = {
                "type": "student",
                "student_no": student.student_no,
                "name": student.name,
                "major_id": student.major_id,
                "class_id": student.class_id,
                "enrollment_year": student.enrollment_year,
            }
    elif user.role == UserRole.TEACHER:
        teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
        if teacher:
            profile = {"type": "teacher", "teacher_no": teacher.teacher_no, "name": teacher.name,
                       "title": teacher.title, "college": teacher.college}
    return {"code": "OK", "message": "success",
            "data": {"user": UserOut.model_validate(user).model_dump(), "profile": profile}}


@router.post("/change-password", response_model=Resp[dict], summary="修改密码")
def change_password(payload: ChangePasswordIn, db: DbSession, user: CurrentUser):
    if not verify_password(payload.old_password, user.password_hash):
        raise AuthError("原密码错误", code="BAD_OLD_PASSWORD")
    if payload.old_password == payload.new_password:
        raise AuthError("新密码不能与原密码相同", code="SAME_PASSWORD")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"code": "OK", "message": "密码修改成功，请重新登录", "data": None}
