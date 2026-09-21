"""开课计划（教学班）接口。

这里有一个典型的**读写分离视角**：
- 管理员看的是"排课视角"（容量、教师、时间地点、已选人数）；
- 学生看的是"选课视角"（我能不能选、还剩多少名额、有没有冲突）。
同一个资源，按角色拼装不同字段，避免前端拿一堆无用数据。
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import AdminUser, CurrentStudent, CurrentUser, DbSession, TeacherUser
from app.core.exceptions import BizError, NotFoundError
from app.models.course import Course
from app.models.enums import CourseType, SemesterStatus, UserRole
from app.models.teaching import CourseOffering, OfferingTimeSlot, Semester
from app.models.user import Student
from app.schemas import OfferingIn, OfferingOut, Resp, TimeSlotOut, OfferingUpdateIn

router = APIRouter(prefix="/offerings", tags=["开课计划"])


# ---------------------------------------------------------------------------
# 装配函数
# ---------------------------------------------------------------------------
def _base_out(offering: CourseOffering) -> dict:
    course = offering.course
    return {
        "id": offering.id,
        "course_id": offering.course_id,
        "course_code": course.code if course else None,
        "course_name": course.name if course else None,
        "credits": course.credits if course else None,
        "course_type": course.course_type if course else None,
        "semester_id": offering.semester_id,
        "semester_code": offering.semester.code if offering.semester else None,
        "teacher_id": offering.teacher_id,
        "teacher_name": offering.teacher.name if offering.teacher else None,
        "class_name": offering.class_name,
        "capacity": offering.capacity,
        "selected_count": offering.selected_count,
        "remaining": offering.remaining,
        "campus": offering.campus,
        "classroom": offering.classroom,
        "major_scope": offering.major_scope,
        "grade_scope": offering.grade_scope,
        "is_open": offering.is_open,
        "remark": offering.remark,
        "time_slots": [TimeSlotOut.model_validate(s).model_dump() for s in offering.time_slots],
        "selected": False,
        "selectable": True,
        "block_reason": None,
    }


def _load_offerings_stmt():
    return select(CourseOffering).options(
        selectinload(CourseOffering.course),
        selectinload(CourseOffering.teacher),
        selectinload(CourseOffering.semester),
        selectinload(CourseOffering.time_slots),
    )


def _replace_time_slots(db: DbSession, offering: CourseOffering, slots) -> None:
    db.execute(OfferingTimeSlot.__table__.delete().where(OfferingTimeSlot.offering_id == offering.id))
    for s in slots:
        s.validate_range()
        db.add(OfferingTimeSlot(
            offering_id=offering.id,
            weekday=s.weekday,
            start_section=s.start_section,
            end_section=s.end_section,
            start_week=s.start_week,
            end_week=s.end_week,
            weeks_desc=f"{s.start_week}-{s.end_week}周",
        ))


def _check_time_slot_self_conflict(slots) -> None:
    """同一教学班自身的时间段也不能互相重叠（避免管理员录错排课）。"""
    for i in range(len(slots)):
        for j in range(i + 1, len(slots)):
            a, b = slots[i], slots[j]
            if a.weekday == b.weekday and not (a.end_section < b.start_section or b.end_section < a.start_section):
                if not (a.end_week < b.start_week or b.end_week < a.start_week):
                    raise BizError(
                        f"排课时间段自相冲突：周{a.weekday} 第{a.start_section}-{a.end_section}节 与 "
                        f"第{b.start_section}-{b.end_section}节",
                        code="SLOT_SELF_CONFLICT",
                    )


# ---------------------------------------------------------------------------
# 管理端
# ---------------------------------------------------------------------------
@router.get("", response_model=Resp[dict], summary="开课计划列表")
def list_offerings(
    db: DbSession,
    _: TeacherUser,
    semester_id: int | None = Query(default=None),
    course_id: int | None = Query(default=None),
    course_type: CourseType | None = Query(default=None),
    keyword: str | None = Query(default=None),
    only_open: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    stmt = _load_offerings_stmt()
    if semester_id:
        stmt = stmt.where(CourseOffering.semester_id == semester_id)
    if course_id:
        stmt = stmt.where(CourseOffering.course_id == course_id)
    if only_open:
        stmt = stmt.where(CourseOffering.is_open.is_(True))
    if course_type or keyword:
        stmt = stmt.join(Course, Course.id == CourseOffering.course_id)
        if course_type:
            stmt = stmt.where(Course.course_type == course_type)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where((Course.name.like(like)) | (Course.code.like(like)))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    offerings = db.execute(
        stmt.order_by(CourseOffering.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return {"code": "OK", "message": "success",
            "data": {"total": total, "page": page, "page_size": page_size,
                     "items": [_base_out(o) for o in offerings]}}


@router.post("", response_model=Resp[OfferingOut], summary="新增开课计划（含排课时间段）")
def create_offering(payload: OfferingIn, db: DbSession, _: AdminUser):
    if db.get(Course, payload.course_id) is None:
        raise NotFoundError("课程不存在")
    if db.get(Semester, payload.semester_id) is None:
        raise NotFoundError("学期不存在")
    _check_time_slot_self_conflict(payload.time_slots)

    offering = CourseOffering(**payload.model_dump(exclude={"time_slots"}))
    db.add(offering)
    db.flush()
    _replace_time_slots(db, offering, payload.time_slots)
    db.commit()
    offering = db.execute(_load_offerings_stmt().where(CourseOffering.id == offering.id)).scalar_one()
    return {"code": "OK", "message": "创建成功", "data": _base_out(offering)}


@router.put("/{offering_id}", response_model=Resp[OfferingOut], summary="修改开课计划")
def update_offering(offering_id: int, payload: OfferingUpdateIn, db: DbSession, _: AdminUser):
    offering = db.execute(_load_offerings_stmt().where(CourseOffering.id == offering_id)).scalar_one_or_none()
    if offering is None:
        raise NotFoundError("开课计划不存在")

    data = payload.model_dump(exclude={"time_slots"}, exclude_none=True)
    if "capacity" in data and data["capacity"] < offering.selected_count:
        raise BizError(
            f"容量不能小于已选人数（当前已选 {offering.selected_count} 人）", code="CAPACITY_TOO_SMALL"
        )
    for k, v in data.items():
        setattr(offering, k, v)

    if payload.time_slots is not None:
        _check_time_slot_self_conflict(payload.time_slots)
        _replace_time_slots(db, offering, payload.time_slots)

    db.commit()
    offering = db.execute(_load_offerings_stmt().where(CourseOffering.id == offering_id)).scalar_one()
    return {"code": "OK", "message": "更新成功", "data": _base_out(offering)}


@router.delete("/{offering_id}", response_model=Resp[dict], summary="删除开课计划")
def delete_offering(offering_id: int, db: DbSession, _: AdminUser):
    offering = db.get(CourseOffering, offering_id)
    if offering is None:
        raise NotFoundError("开课计划不存在")
    if offering.selected_count > 0:
        raise BizError("该教学班已有学生选课，请先关闭选课而不是删除", code="OFFERING_IN_USE")
    db.delete(offering)
    db.commit()
    return {"code": "OK", "message": "删除成功", "data": None}


# ---------------------------------------------------------------------------
# 学生端
# ---------------------------------------------------------------------------
@router.get("/selectable", response_model=Resp[list[OfferingOut]], summary="学生：可选课程列表（带可选择性标注）")
def list_selectable(
    db: DbSession,
    student: CurrentStudent,
    semester_id: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
    course_type: CourseType | None = Query(default=None),
    only_selectable: bool = Query(default=False),
):
    """列表接口也带上"能不能选"的判断，学生不用点进去才知道被拦。

    实现上复用同一套规则引擎：批量装配一次状态快照，再对每个教学班跑规则，
    避免逐条查库。
    """
    from app.services.academic import build_academic_state
    from app.services.rule_engine import BLOCK, RuleEngine, RuleContext
    from app.models.course import CoursePrerequisite

    semester = db.get(Semester, semester_id) if semester_id else _current(db)
    if semester is None:
        raise NotFoundError("尚未配置学期")

    state = build_academic_state(db, student, semester)
    engine = RuleEngine.from_db(db, {"max_credits": state.max_credits})

    stmt = _load_offerings_stmt().where(
        CourseOffering.semester_id == semester.id, CourseOffering.is_open.is_(True)
    )
    if course_type or keyword:
        stmt = stmt.join(Course, Course.id == CourseOffering.course_id)
        if course_type:
            stmt = stmt.where(Course.course_type == course_type)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where((Course.name.like(like)) | (Course.code.like(like)))

    offerings = db.execute(stmt.order_by(CourseOffering.id)).scalars().all()

    # 一次性把全部先修课关系取出来，避免循环内查询
    prereq_rows = db.execute(
        select(CoursePrerequisite).options(selectinload(CoursePrerequisite.prerequisite))
        .where(CoursePrerequisite.course_id.in_([o.course_id for o in offerings] or [0]))
    ).scalars().all()
    prereq_map: dict[int, list] = {}
    for p in prereq_rows:
        prereq_map.setdefault(p.course_id, []).append(p)

    items = []
    for offering in offerings:
        data = _base_out(offering)
        ctx = RuleContext(state=state, offering=offering, course=offering.course,
                          prerequisites=prereq_map.get(offering.course_id, []), params={})
        ok, results = engine.evaluate(ctx)
        blocking = [r for r in results if not r.passed and r.level == BLOCK]
        warnings = [r.message for r in results if not r.passed and r.level != BLOCK and r.message]
        data["selected"] = offering.course_id in state.selected_course_ids
        data["selectable"] = ok
        data["block_reason"] = blocking[0].message if blocking else None
        data["warnings"] = warnings
        if data["selected"]:
            data["block_reason"] = "本学期已选该课程"
        if only_selectable and not ok:
            continue
        items.append(data)
    return {"code": "OK", "message": "success", "data": items}


@router.get("/{offering_id}", response_model=Resp[OfferingOut], summary="开课计划详情")
def get_offering(offering_id: int, db: DbSession, user: CurrentUser):
    """学生视角查询时会附上"我能不能选 + 为什么"；其他角色看到纯管理字段。"""
    offering = db.execute(_load_offerings_stmt().where(CourseOffering.id == offering_id)).scalar_one_or_none()
    if offering is None:
        raise NotFoundError("开课计划不存在")
    data = _base_out(offering)

    if user.role == UserRole.STUDENT:
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is not None:
            from app.services.selection_service import evaluate_offering

            ok, results, state = evaluate_offering(db, student, offering)
            data["selectable"] = ok
            data["block_reason"] = next(
                (r.message for r in results if not r.passed and r.level == BLOCK), None
            )
            data["selected"] = offering.course_id in state.selected_course_ids
    return {"code": "OK", "message": "success", "data": data}


def _current(db: DbSession) -> Semester | None:
    sem = db.execute(select(Semester).where(Semester.is_current.is_(True))).scalar_one_or_none()
    if sem:
        return sem
    return db.execute(
        select(Semester).where(Semester.status == SemesterStatus.SELECTING).order_by(Semester.start_date.desc())
    ).scalars().first()
