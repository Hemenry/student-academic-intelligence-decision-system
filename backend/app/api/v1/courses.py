"""课程库管理接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import AdminUser, DbSession, TeacherUser
from app.core.exceptions import BizError, NotFoundError
from app.models.course import Course, CoursePrerequisite
from app.models.enums import CourseType
from app.models.teaching import CourseOffering
from app.schemas import CourseIn, CourseOut, PrerequisiteIn, Resp

router = APIRouter(prefix="/courses", tags=["课程库"])


def _to_out(course: Course, prereq_names: list[str] | None = None,
            prereq_rows: list[CoursePrerequisite] | None = None) -> dict:
    data = CourseOut.model_validate(course).model_dump()
    data["prerequisite_names"] = prereq_names or []
    data["prerequisites"] = [
        {
            "prerequisite_course_id": p.prerequisite_course_id,
            "prerequisite_course_name": p.prerequisite.name if p.prerequisite else None,
            "prerequisite_course_code": p.prerequisite.code if p.prerequisite else None,
            "min_score": p.min_score,
            "allow_concurrent": p.allow_concurrent,
        }
        for p in (prereq_rows or [])
    ]
    return data


@router.get("", response_model=Resp[dict], summary="课程列表（分页/关键字/类别筛选）")
def list_courses(
    db: DbSession,
    _: TeacherUser,
    keyword: str | None = Query(default=None, description="课程名或代码模糊搜索"),
    course_type: CourseType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    stmt = select(Course)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where((Course.name.like(like)) | (Course.code.like(like)))
    if course_type:
        stmt = stmt.where(Course.course_type == course_type)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    courses = db.execute(
        stmt.order_by(Course.code).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    # 一次性把先修课名查出来，避免逐条查询造成 N+1
    prereq_map = _prereq_name_map(db, [c.id for c in courses])
    items = [_to_out(c, prereq_map.get(c.id)) for c in courses]
    return {"code": "OK", "message": "success",
            "data": {"total": total, "page": page, "page_size": page_size, "items": items}}


def _prereq_name_map(db: DbSession, course_ids: list[int]) -> dict[int, list[str]]:
    if not course_ids:
        return {}
    rows = db.execute(
        select(CoursePrerequisite.course_id, Course.name)
        .join(Course, Course.id == CoursePrerequisite.prerequisite_course_id)
        .where(CoursePrerequisite.course_id.in_(course_ids))
    ).all()
    result: dict[int, list[str]] = {}
    for cid, name in rows:
        result.setdefault(cid, []).append(name)
    return result


@router.get("/{course_id}", response_model=Resp[CourseOut], summary="课程详情")
def get_course(course_id: int, db: DbSession, _: TeacherUser):
    course = db.execute(
        select(Course).options(selectinload(Course.prereq_links).selectinload(CoursePrerequisite.prerequisite))
        .where(Course.id == course_id)
    ).scalar_one_or_none()
    if course is None:
        raise NotFoundError("课程不存在")
    names = [p.prerequisite.name for p in course.prereq_links if p.prerequisite]
    return {"code": "OK", "message": "success", "data": _to_out(course, names, course.prereq_links)}


@router.post("", response_model=Resp[CourseOut], summary="新增课程")
def create_course(payload: CourseIn, db: DbSession, _: AdminUser):
    if db.execute(select(Course).where(Course.code == payload.code)).scalar_one_or_none():
        raise BizError(f"课程代码 {payload.code} 已存在", code="COURSE_CODE_EXISTS")
    course = Course(**payload.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return {"code": "OK", "message": "创建成功", "data": _to_out(course)}


@router.put("/{course_id}", response_model=Resp[CourseOut], summary="修改课程")
def update_course(course_id: int, payload: CourseIn, db: DbSession, _: AdminUser):
    course = db.get(Course, course_id)
    if course is None:
        raise NotFoundError("课程不存在")
    for k, v in payload.model_dump().items():
        setattr(course, k, v)
    db.commit()
    db.refresh(course)
    return {"code": "OK", "message": "更新成功", "data": _to_out(course)}


@router.delete("/{course_id}", response_model=Resp[dict], summary="删除课程")
def delete_course(course_id: int, db: DbSession, _: AdminUser):
    course = db.get(Course, course_id)
    if course is None:
        raise NotFoundError("课程不存在")
    used = db.execute(
        select(func.count(CourseOffering.id)).where(CourseOffering.course_id == course_id)
    ).scalar_one()
    if used:
        raise BizError(f"该课程已有 {used} 条开课记录，无法删除（可改为停用）", code="COURSE_IN_USE")
    db.delete(course)
    db.commit()
    return {"code": "OK", "message": "删除成功", "data": None}


@router.put("/{course_id}/prerequisites", response_model=Resp[dict], summary="配置先修课")
def set_prerequisites(course_id: int, payload: list[PrerequisiteIn], db: DbSession, _: AdminUser):
    """整表覆盖式配置，事务内先删后插，避免部分更新的中间态。"""
    course = db.get(Course, course_id)
    if course is None:
        raise NotFoundError("课程不存在")
    for item in payload:
        if item.prerequisite_course_id == course_id:
            raise BizError("先修课不能是课程自身", code="SELF_PREREQUISITE")
        if db.get(Course, item.prerequisite_course_id) is None:
            raise NotFoundError(f"先修课 {item.prerequisite_course_id} 不存在")

    db.execute(
        CoursePrerequisite.__table__.delete().where(CoursePrerequisite.course_id == course_id)
    )
    for item in payload:
        db.add(CoursePrerequisite(course_id=course_id, **item.model_dump()))
    db.commit()
    return {"code": "OK", "message": f"已配置 {len(payload)} 门先修课", "data": None}
