"""学期管理接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select, update

from app.core.deps import AdminUser, CurrentUser, DbSession
from app.core.exceptions import BizError, NotFoundError
from app.models.enums import SemesterStatus
from app.models.teaching import CourseOffering, Semester
from app.schemas import Resp, SemesterIn, SemesterOut

router = APIRouter(prefix="/semesters", tags=["学期管理"])


def _to_out(sem: Semester, offering_count: int = 0) -> dict:
    data = SemesterOut.model_validate(sem).model_dump()
    data["offering_count"] = offering_count
    return data


# 学期信息不涉及敏感数据，且学生端「我的成绩 / 我的课表」需要按学期筛选，
# 因此读接口对所有已登录角色开放，写操作仍然只允许管理员
@router.get("", response_model=Resp[list[SemesterOut]], summary="学期列表（所有登录角色可见）")
def list_semesters(db: DbSession, user: CurrentUser):
    semesters = db.execute(select(Semester).order_by(Semester.start_date.desc())).scalars().all()
    counts = dict(db.execute(
        select(CourseOffering.semester_id, func.count(CourseOffering.id)).group_by(CourseOffering.semester_id)
    ).all())
    return {"code": "OK", "message": "success",
            "data": [_to_out(s, counts.get(s.id, 0)) for s in semesters]}


@router.get("/current", response_model=Resp[SemesterOut], summary="当前学期（所有登录角色可见）")
def current_semester(db: DbSession, user: CurrentUser):
    sem = db.execute(select(Semester).where(Semester.is_current.is_(True))).scalar_one_or_none()
    if sem is None:
        sem = db.execute(select(Semester).order_by(Semester.start_date.desc())).scalars().first()
    if sem is None:
        raise NotFoundError("尚未配置任何学期")
    return {"code": "OK", "message": "success", "data": _to_out(sem)}


@router.post("", response_model=Resp[SemesterOut], summary="新增学期")
def create_semester(payload: SemesterIn, db: DbSession, _: AdminUser):
    if payload.end_date <= payload.start_date:
        raise BizError("结束日期必须晚于开始日期", code="INVALID_DATE_RANGE")
    if db.execute(select(Semester).where(Semester.code == payload.code)).scalar_one_or_none():
        raise BizError(f"学期代码 {payload.code} 已存在", code="SEMESTER_CODE_EXISTS")

    sem = Semester(**payload.model_dump())
    db.add(sem)
    db.flush()
    # 保证"当前学期"全局唯一：设置新的时把旧的取消
    if payload.is_current:
        db.execute(
            update(Semester).where(Semester.id != sem.id).values(is_current=False)
        )
    db.commit()
    db.refresh(sem)
    return {"code": "OK", "message": "创建成功", "data": _to_out(sem)}


@router.put("/{semester_id}", response_model=Resp[SemesterOut], summary="修改学期")
def update_semester(semester_id: int, payload: SemesterIn, db: DbSession, _: AdminUser):
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise NotFoundError("学期不存在")
    for k, v in payload.model_dump().items():
        setattr(sem, k, v)
    if payload.is_current:
        db.execute(update(Semester).where(Semester.id != semester_id).values(is_current=False))
    db.commit()
    db.refresh(sem)
    return {"code": "OK", "message": "更新成功", "data": _to_out(sem)}


@router.post("/{semester_id}/open-selection", response_model=Resp[SemesterOut], summary="开启选课")
def open_selection(
    semester_id: int,
    db: DbSession,
    _: AdminUser,
    select_start_at: str | None = Query(default=None, description="ISO 时间，如 2026-09-01T08:00:00"),
    select_end_at: str | None = Query(default=None),
):
    """把学期状态切到 SELECTING —— 规则引擎的"选课时间窗口"规则据此放行。"""
    from datetime import datetime

    sem = db.get(Semester, semester_id)
    if sem is None:
        raise NotFoundError("学期不存在")
    sem.status = SemesterStatus.SELECTING
    if select_start_at:
        sem.select_start_at = datetime.fromisoformat(select_start_at)
    if select_end_at:
        sem.select_end_at = datetime.fromisoformat(select_end_at)
    db.commit()
    db.refresh(sem)
    return {"code": "OK", "message": "选课已开启", "data": _to_out(sem)}


@router.post("/{semester_id}/close-selection", response_model=Resp[SemesterOut], summary="关闭选课")
def close_selection(semester_id: int, db: DbSession, _: AdminUser):
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise NotFoundError("学期不存在")
    sem.status = SemesterStatus.ONGOING
    db.commit()
    db.refresh(sem)
    return {"code": "OK", "message": "选课已关闭", "data": _to_out(sem)}
