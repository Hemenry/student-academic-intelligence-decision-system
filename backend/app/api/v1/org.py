"""专业与班级管理接口（教务管理员）。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import AdminUser, DbSession, TeacherUser
from app.core.exceptions import BizError, NotFoundError
from app.models.org import ClassGroup, Major
from app.models.user import Student, Teacher
from app.schemas import ClassIn, ClassOut, MajorIn, MajorOut, Resp, TeacherBrief

router = APIRouter(tags=["组织管理"])


@router.get("/teachers", response_model=Resp[list[TeacherBrief]], summary="教师列表（开课排课用）")
def list_teachers(db: DbSession, _: TeacherUser):
    teachers = db.execute(select(Teacher).order_by(Teacher.teacher_no)).scalars().all()
    return {"code": "OK", "message": "success",
            "data": [TeacherBrief.model_validate(t).model_dump() for t in teachers]}


def _major_to_out(m: Major) -> dict:
    return MajorOut.model_validate(m).model_dump()


# ============================== 专业 ==============================
@router.get("/majors", response_model=Resp[list[MajorOut]], summary="专业列表")
def list_majors(db: DbSession, _: TeacherUser):
    majors = db.execute(select(Major).order_by(Major.code)).scalars().all()
    return {"code": "OK", "message": "success", "data": [_major_to_out(m) for m in majors]}


@router.post("/majors", response_model=Resp[MajorOut], summary="新增专业")
def create_major(payload: MajorIn, db: DbSession, _: AdminUser):
    if db.execute(select(Major).where(Major.code == payload.code)).scalar_one_or_none():
        raise BizError(f"专业代码 {payload.code} 已存在", code="MAJOR_CODE_EXISTS")
    major = Major(**payload.model_dump())
    db.add(major)
    db.commit()
    db.refresh(major)
    return {"code": "OK", "message": "创建成功", "data": _major_to_out(major)}


@router.put("/majors/{major_id}", response_model=Resp[MajorOut], summary="修改专业")
def update_major(major_id: int, payload: MajorIn, db: DbSession, _: AdminUser):
    major = db.get(Major, major_id)
    if major is None:
        raise NotFoundError("专业不存在")
    for k, v in payload.model_dump().items():
        setattr(major, k, v)
    db.commit()
    db.refresh(major)
    return {"code": "OK", "message": "更新成功", "data": _major_to_out(major)}


@router.delete("/majors/{major_id}", response_model=Resp[dict], summary="删除专业")
def delete_major(major_id: int, db: DbSession, _: AdminUser):
    major = db.get(Major, major_id)
    if major is None:
        raise NotFoundError("专业不存在")
    student_count = db.execute(
        select(func.count(Student.id)).where(Student.major_id == major_id)
    ).scalar_one()
    if student_count:
        raise BizError(f"该专业下还有 {student_count} 名学生，无法删除", code="MAJOR_IN_USE")
    db.delete(major)
    db.commit()
    return {"code": "OK", "message": "删除成功", "data": None}


# ============================== 班级 ==============================
@router.get("/classes", response_model=Resp[list[ClassOut]], summary="班级列表")
def list_classes(
    db: DbSession,
    _: TeacherUser,
    major_id: int | None = Query(default=None),
    grade_year: int | None = Query(default=None),
):
    stmt = select(ClassGroup).order_by(ClassGroup.grade_year.desc(), ClassGroup.name)
    if major_id:
        stmt = stmt.where(ClassGroup.major_id == major_id)
    if grade_year:
        stmt = stmt.where(ClassGroup.grade_year == grade_year)
    classes = db.execute(stmt).scalars().all()

    major_map = {m.id: m.name for m in db.execute(select(Major)).scalars().all()}
    counts = dict(db.execute(
        select(Student.class_id, func.count(Student.id)).group_by(Student.class_id)
    ).all())

    data = []
    for c in classes:
        item = ClassOut.model_validate(c).model_dump()
        item["major_name"] = major_map.get(c.major_id)
        item["student_count"] = counts.get(c.id, 0)
        data.append(item)
    return {"code": "OK", "message": "success", "data": data}


@router.post("/classes", response_model=Resp[ClassOut], summary="新增班级")
def create_class(payload: ClassIn, db: DbSession, _: AdminUser):
    if db.get(Major, payload.major_id) is None:
        raise NotFoundError("专业不存在")
    if db.execute(
        select(ClassGroup).where(ClassGroup.name == payload.name, ClassGroup.major_id == payload.major_id)
    ).scalar_one_or_none():
        raise BizError("该专业下已存在同名班级", code="CLASS_EXISTS")
    klass = ClassGroup(**payload.model_dump())
    db.add(klass)
    db.commit()
    db.refresh(klass)
    return {"code": "OK", "message": "创建成功", "data": ClassOut.model_validate(klass).model_dump()}


@router.put("/classes/{class_id}", response_model=Resp[ClassOut], summary="修改班级")
def update_class(class_id: int, payload: ClassIn, db: DbSession, _: AdminUser):
    klass = db.get(ClassGroup, class_id)
    if klass is None:
        raise NotFoundError("班级不存在")
    for k, v in payload.model_dump().items():
        setattr(klass, k, v)
    db.commit()
    db.refresh(klass)
    return {"code": "OK", "message": "更新成功", "data": ClassOut.model_validate(klass).model_dump()}


@router.delete("/classes/{class_id}", response_model=Resp[dict], summary="删除班级")
def delete_class(class_id: int, db: DbSession, _: AdminUser):
    klass = db.get(ClassGroup, class_id)
    if klass is None:
        raise NotFoundError("班级不存在")
    count = db.execute(select(func.count(Student.id)).where(Student.class_id == class_id)).scalar_one()
    if count:
        raise BizError(f"该班级下还有 {count} 名学生，无法删除", code="CLASS_IN_USE")
    db.delete(klass)
    db.commit()
    return {"code": "OK", "message": "删除成功", "data": None}
