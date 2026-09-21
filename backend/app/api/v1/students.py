"""学生档案管理接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import AdminUser, DbSession, TeacherUser
from app.core.exceptions import BizError, NotFoundError
from app.core.security import hash_password
from app.models.enums import StudentStatus, UserRole
from app.models.org import ClassGroup, Major
from app.models.user import Student, SysUser
from app.schemas import Resp, StudentCreateIn, StudentOut, StudentUpdateIn

router = APIRouter(prefix="/students", tags=["学生管理"])


def _to_out(student: Student, major_name: str | None = None, class_name: str | None = None) -> dict:
    data = StudentOut.model_validate(student).model_dump()
    data["major_name"] = major_name
    data["class_name"] = class_name
    return data


@router.get("", response_model=Resp[dict], summary="学生列表（分页/多条件筛选）")
def list_students(
    db: DbSession,
    _: TeacherUser,
    keyword: str | None = Query(default=None, description="学号或姓名"),
    major_id: int | None = Query(default=None),
    class_id: int | None = Query(default=None),
    grade_year: int | None = Query(default=None),
    status: StudentStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    stmt = select(Student)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where((Student.name.like(like)) | (Student.student_no.like(like)))
    if major_id:
        stmt = stmt.where(Student.major_id == major_id)
    if class_id:
        stmt = stmt.where(Student.class_id == class_id)
    if grade_year:
        stmt = stmt.where(Student.enrollment_year == grade_year)
    if status:
        stmt = stmt.where(Student.status == status)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    students = db.execute(
        stmt.order_by(Student.student_no).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    major_map = {m.id: m.name for m in db.execute(select(Major)).scalars().all()}
    class_map = {c.id: c.name for c in db.execute(select(ClassGroup)).scalars().all()}
    items = [_to_out(s, major_map.get(s.major_id), class_map.get(s.class_id)) for s in students]
    return {"code": "OK", "message": "success",
            "data": {"total": total, "page": page, "page_size": page_size, "items": items}}


@router.get("/{student_id}", response_model=Resp[StudentOut], summary="学生详情")
def get_student(student_id: int, db: DbSession, _: TeacherUser):
    student = db.get(Student, student_id)
    if student is None:
        raise NotFoundError("学生不存在")
    major = db.get(Major, student.major_id)
    klass = db.get(ClassGroup, student.class_id) if student.class_id else None
    return {"code": "OK", "message": "success",
            "data": _to_out(student, major.name if major else None, klass.name if klass else None)}


@router.post("", response_model=Resp[StudentOut], summary="新增学生（同时创建登录账号）")
def create_student(payload: StudentCreateIn, db: DbSession, _: AdminUser):
    """新增学生时一并创建 sys_user 账号，默认密码 123456（首次登录建议强制修改）。

    事务性：账号与档案必须同生共死，任一失败整体回滚，
    否则会出现"有账号没档案"或"有档案登不上"的脏数据。
    """
    if db.get(Major, payload.major_id) is None:
        raise NotFoundError("专业不存在")
    if payload.class_id and db.get(ClassGroup, payload.class_id) is None:
        raise NotFoundError("班级不存在")
    if db.execute(select(Student).where(Student.student_no == payload.student_no)).scalar_one_or_none():
        raise BizError(f"学号 {payload.student_no} 已存在", code="STUDENT_NO_EXISTS")
    if db.execute(select(SysUser).where(SysUser.username == payload.username)).scalar_one_or_none():
        raise BizError(f"登录账号 {payload.username} 已被占用", code="USERNAME_EXISTS")

    user = SysUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.name,
        role=UserRole.STUDENT,
    )
    db.add(user)
    db.flush()  # 先拿到 user.id，再建档案，保持同一事务

    student = Student(
        user_id=user.id,
        student_no=payload.student_no,
        name=payload.name,
        gender=payload.gender,
        major_id=payload.major_id,
        class_id=payload.class_id,
        enrollment_year=payload.enrollment_year,
        phone=payload.phone,
        email=payload.email,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    major = db.get(Major, student.major_id)
    klass = db.get(ClassGroup, student.class_id) if student.class_id else None
    return {"code": "OK", "message": "创建成功",
            "data": _to_out(student, major.name if major else None, klass.name if klass else None)}


@router.put("/{student_id}", response_model=Resp[StudentOut], summary="修改学生档案")
def update_student(student_id: int, payload: StudentUpdateIn, db: DbSession, _: AdminUser):
    student = db.get(Student, student_id)
    if student is None:
        raise NotFoundError("学生不存在")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(student, k, v)
    db.commit()
    db.refresh(student)
    return {"code": "OK", "message": "更新成功", "data": _to_out(student)}


@router.post("/{student_id}/reset-password", response_model=Resp[dict], summary="重置学生密码")
def reset_password(student_id: int, db: DbSession, _: AdminUser, new_password: str = Query(default="123456")):
    student = db.get(Student, student_id)
    if student is None:
        raise NotFoundError("学生不存在")
    user = db.get(SysUser, student.user_id)
    if user is None:
        raise NotFoundError("学生账号不存在")
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"code": "OK", "message": "密码已重置", "data": None}


@router.delete("/{student_id}", response_model=Resp[dict], summary="删除学生")
def delete_student(student_id: int, db: DbSession, _: AdminUser):
    student = db.get(Student, student_id)
    if student is None:
        raise NotFoundError("学生不存在")
    user = db.get(SysUser, student.user_id)
    db.delete(student)
    if user:
        db.delete(user)
    db.commit()
    return {"code": "OK", "message": "删除成功", "data": None}
