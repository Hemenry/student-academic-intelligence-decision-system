"""选课接口：智能选课、退课、课表、选课体检。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import AdminUser, CurrentStudent, DbSession, TeacherUser
from app.core.exceptions import NotFoundError
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.enums import EnrollmentStatus
from app.models.teaching import CourseOffering, Semester
from app.models.user import Student
from app.schemas import (
    DropCourseIn,
    EnrollmentOut,
    PrecheckOut,
    Resp,
    SelectCourseIn,
    TimeSlotOut,
)
from app.services import selection_service

router = APIRouter(prefix="/enrollments", tags=["选课"])


def _to_out(en: Enrollment) -> dict:
    course = en.course
    offering = en.offering
    return {
        "id": en.id,
        "student_id": en.student_id,
        "offering_id": en.offering_id,
        "course_id": en.course_id,
        "semester_id": en.semester_id,
        "status": en.status,
        "enroll_type": en.enroll_type,
        "credits": en.credits,
        "select_at": en.select_at,
        "drop_at": en.drop_at,
        "course_code": course.code if course else None,
        "course_name": course.name if course else None,
        "course_type": course.course_type if course else None,
        "teacher_name": (offering.teacher.name if offering and offering.teacher else None),
        "class_name": offering.class_name if offering else None,
        "final_score": en.grade.final_score if en.grade else None,
        "grade_point": en.grade.grade_point if en.grade else None,
        "time_slots": [TimeSlotOut.model_validate(s).model_dump() for s in (offering.time_slots if offering else [])],
    }


# ============================== 学生端 ==============================
@router.post("/select", response_model=Resp[EnrollmentOut], summary="学生：选课")
def select_course(payload: SelectCourseIn, db: DbSession, student: CurrentStudent):
    """选课核心接口。并发安全细节见 app/services/selection_service.py。

    接口本身很"薄"——校验与并发控制全在 service 层，
    这样同一套选课逻辑可以被定时任务、批量导入等入口复用，不受 HTTP 层约束。
    """
    enrollment = selection_service.select_course(
        db, student, payload.offering_id, idempotent_key=payload.idempotent_key
    )
    enrollment = db.execute(
        select(Enrollment)
        .options(
            selectinload(Enrollment.course),
            selectinload(Enrollment.grade),
            selectinload(Enrollment.offering).selectinload(CourseOffering.time_slots),
            selectinload(Enrollment.offering).selectinload(CourseOffering.teacher),
        )
        .where(Enrollment.id == enrollment.id)
    ).scalar_one()
    return {"code": "OK", "message": f"选课成功：{enrollment.course.name}", "data": _to_out(enrollment)}


@router.post("/drop", response_model=Resp[dict], summary="学生：退课")
def drop_course(payload: DropCourseIn, db: DbSession, student: CurrentStudent):
    selection_service.drop_course(db, student, payload.offering_id, payload.reason)
    return {"code": "OK", "message": "退课成功", "data": None}


@router.get("/my", response_model=Resp[list[EnrollmentOut]], summary="学生：我的选课记录")
def my_enrollments(
    db: DbSession,
    student: CurrentStudent,
    semester_id: int | None = Query(default=None, description="不传则默认当前学期"),
    all_semesters: bool = Query(default=False, description="是否包含全部学期的历史记录"),
):
    items = selection_service.list_my_enrollments(db, student, semester_id, all_semesters=all_semesters)
    return {"code": "OK", "message": "success", "data": [_to_out(e) for e in items]}


@router.get("/timetable", response_model=Resp[dict], summary="学生：个人课表")
def my_timetable(
    db: DbSession,
    student: CurrentStudent,
    semester_id: int | None = Query(default=None, description="不传则默认当前学期"),
):
    return {"code": "OK", "message": "success",
            "data": selection_service.build_timetable(db, student, semester_id)}


@router.post("/precheck", response_model=Resp[PrecheckOut], summary="学生：选课预检（试跑规则引擎）")
def precheck(payload: SelectCourseIn, db: DbSession, student: CurrentStudent):
    """不写库地跑一遍完整规则，返回逐条校验结果。

    这是"智能决策"的学生侧体现：把"能不能选、为什么不能"提前讲清楚，
    而不是提交失败才弹一个笼统的报错。
    """
    offering = selection_service.load_offering(db, payload.offering_id)
    if offering is None:
        raise NotFoundError("教学班不存在")
    ok, results, state = selection_service.evaluate_offering(db, student, offering)
    return {
        "code": "OK",
        "message": "预检完成",
        "data": {
            "offering_id": offering.id,
            "selectable": ok,
            "checks": [r.to_dict() for r in results],
            "current_credits": round(state.current_credits, 1),
            "max_credits": state.max_credits,
        },
    }


# ============================== 管理端 ==============================
@router.get("", response_model=Resp[dict], summary="管理员：选课记录查询")
def list_enrollments(
    db: DbSession,
    _: TeacherUser,
    semester_id: int | None = Query(default=None),
    offering_id: int | None = Query(default=None),
    student_id: int | None = Query(default=None),
    class_id: int | None = Query(default=None),
    status: EnrollmentStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    stmt = (
        select(Enrollment)
        .options(
            selectinload(Enrollment.course),
            selectinload(Enrollment.grade),
            selectinload(Enrollment.offering).selectinload(CourseOffering.teacher),
            selectinload(Enrollment.offering).selectinload(CourseOffering.time_slots),
        )
        .order_by(Enrollment.id.desc())
    )
    if semester_id:
        stmt = stmt.where(Enrollment.semester_id == semester_id)
    if offering_id:
        stmt = stmt.where(Enrollment.offering_id == offering_id)
    if student_id:
        stmt = stmt.where(Enrollment.student_id == student_id)
    if status:
        stmt = stmt.where(Enrollment.status == status)
    if class_id:
        stmt = stmt.join(Student, Student.id == Enrollment.student_id).where(Student.class_id == class_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()

    student_map = {}
    student_ids = {e.student_id for e in rows}
    if student_ids:
        student_map = {
            s.id: s for s in db.execute(select(Student).where(Student.id.in_(student_ids))).scalars().all()
        }

    items = []
    for e in rows:
        item = _to_out(e)
        stu = student_map.get(e.student_id)
        item["student_no"] = stu.student_no if stu else None
        item["student_name"] = stu.name if stu else None
        items.append(item)
    return {"code": "OK", "message": "success",
            "data": {"total": total, "page": page, "page_size": page_size, "items": items}}


@router.get("/stats/by-course", response_model=Resp[list[dict]], summary="管理员：开课选课情况统计")
def stats_by_course(db: DbSession, _: TeacherUser, semester_id: int | None = Query(default=None)):
    """选课热度排行：选课率、余量，帮助教务处决定是否加开班次。"""
    stmt = (
        select(CourseOffering, Course, Semester)
        .join(Course, Course.id == CourseOffering.course_id)
        .join(Semester, Semester.id == CourseOffering.semester_id)
    )
    if semester_id:
        stmt = stmt.where(CourseOffering.semester_id == semester_id)
    rows = db.execute(stmt).all()

    data = []
    for offering, course, semester in rows:
        ratio = offering.selected_count / offering.capacity if offering.capacity else 0
        data.append({
            "offering_id": offering.id,
            "course_code": course.code,
            "course_name": course.name,
            "course_type": course.course_type,
            "semester_code": semester.code,
            "capacity": offering.capacity,
            "selected_count": offering.selected_count,
            "remaining": offering.remaining,
            "select_ratio": round(ratio * 100, 1),
            "teacher_name": offering.teacher.name if offering.teacher else None,
        })
    data.sort(key=lambda x: x["select_ratio"], reverse=True)
    return {"code": "OK", "message": "success", "data": data}
