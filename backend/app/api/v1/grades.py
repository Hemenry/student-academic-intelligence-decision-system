"""成绩管理接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import AdminUser, CurrentStudent, DbSession, TeacherUser
from app.core.exceptions import NotFoundError
from app.models.course import Course
from app.models.enrollment import Enrollment, Grade
from app.models.enums import CourseType, EnrollmentStatus
from app.models.teaching import Semester
from app.models.user import Student
from app.schemas import BatchGradeIn, GpaStatOut, GradeIn, GradeOut, Resp
from app.services import grade_service

router = APIRouter(prefix="/grades", tags=["成绩管理"])


def _to_out(grade: Grade) -> dict:
    course = grade.course
    data = GradeOut.model_validate(grade).model_dump()
    data["course_code"] = course.code if course else None
    data["course_name"] = course.name if course else None
    data["course_type"] = course.course_type if course else None
    return data


# ============================== 学生端 ==============================
@router.get("/my", response_model=Resp[list[GradeOut]], summary="学生：我的成绩单")
def my_grades(
    db: DbSession,
    student: CurrentStudent,
    semester_id: int | None = Query(default=None),
    course_type: CourseType | None = Query(default=None),
):
    grades = grade_service.list_student_grades(db, student.id, semester_id, course_type)
    sem_map = {s.id: s.name for s in db.execute(select(Semester)).scalars().all()}
    items = []
    for g in grades:
        item = _to_out(g)
        item["semester_name"] = sem_map.get(g.semester_id)
        items.append(item)
    return {"code": "OK", "message": "success", "data": items}


@router.get("/my/gpa", response_model=Resp[GpaStatOut], summary="学生：GPA 与学分统计")
def my_gpa(db: DbSession, student: CurrentStudent):
    return {"code": "OK", "message": "success", "data": grade_service.gpa_stat(db, student)}


@router.get("/my/failed", response_model=Resp[list[GradeOut]], summary="学生：挂科清单（重修提醒）")
def my_failed(db: DbSession, student: CurrentStudent):
    return {"code": "OK", "message": "success",
            "data": [_to_out(g) for g in grade_service.failed_courses(db, student.id)]}


# ============================== 教师/管理端 ==============================
@router.put("/record", response_model=Resp[GradeOut], summary="教师：录入成绩（单条）")
def record_grade(payload: GradeIn, db: DbSession, user: TeacherUser):
    grade = grade_service.record_grade(
        db,
        enrollment_id=payload.enrollment_id,
        usual_score=payload.usual_score,
        exam_score=payload.exam_score,
        final_score=payload.final_score,
        usual_weight=payload.usual_weight,
        recorder_id=user.id,
        remark=payload.remark,
    )
    db.refresh(grade)
    return {"code": "OK", "message": "成绩已录入", "data": _to_out(grade)}


@router.put("/batch-record", response_model=Resp[dict], summary="教师：批量录入成绩")
def batch_record(payload: BatchGradeIn, db: DbSession, user: TeacherUser):
    """逐条录入，单条失败不影响其他条，最后统一返回成功/失败清单。

    教务场景里老师一次要录几十条，不能因为一条数据有问题就整批回滚重来。
    """
    success, failed = 0, []
    for item in payload.items:
        try:
            grade_service.record_grade(
                db,
                enrollment_id=item.enrollment_id,
                usual_score=item.usual_score,
                exam_score=item.exam_score,
                final_score=item.final_score,
                usual_weight=item.usual_weight,
                recorder_id=user.id,
                remark=item.remark,
            )
            success += 1
        except Exception as exc:
            db.rollback()
            failed.append({"enrollment_id": item.enrollment_id, "error": str(exc)})
    return {"code": "OK", "message": f"成功 {success} 条，失败 {len(failed)} 条",
            "data": {"success": success, "failed": failed}}


@router.get("/offering/{offering_id}/roster", response_model=Resp[list[dict]], summary="教师：教学班花名册（含成绩）")
def offering_roster(offering_id: int, db: DbSession, _: TeacherUser):
    rows = db.execute(
        select(Enrollment, Student)
        .join(Student, Student.id == Enrollment.student_id)
        .options(selectinload(Enrollment.grade))
        .where(Enrollment.offering_id == offering_id, Enrollment.status != EnrollmentStatus.DROPPED)
        .order_by(Student.student_no)
    ).all()
    return {
        "code": "OK",
        "message": "success",
        "data": [
            {
                "enrollment_id": en.id,
                "student_id": stu.id,
                "student_no": stu.student_no,
                "student_name": stu.name,
                "usual_score": en.grade.usual_score if en.grade else None,
                "exam_score": en.grade.exam_score if en.grade else None,
                "final_score": en.grade.final_score if en.grade else None,
                "grade_point": en.grade.grade_point if en.grade else None,
                "is_pass": en.grade.is_pass if en.grade else None,
            }
            for en, stu in rows
        ],
    }


@router.get("/stats/course/{course_id}", response_model=Resp[dict], summary="管理端：课程成绩分析")
def course_stat(course_id: int, db: DbSession, _: TeacherUser, semester_id: int | None = Query(default=None)):
    """成绩分布：平均分、及格率、分档人数，教务评估教学效果的基础数据。"""
    course = db.get(Course, course_id)
    if course is None:
        raise NotFoundError("课程不存在")

    stmt = select(Grade).where(Grade.course_id == course_id)
    if semester_id:
        stmt = stmt.where(Grade.semester_id == semester_id)
    grades = db.execute(stmt).scalars().all()
    if not grades:
        return {"code": "OK", "message": "暂无成绩数据",
                "data": {"course_name": course.name, "total": 0, "average": 0, "pass_rate": 0, "distribution": {}}}

    scores = [g.final_score for g in grades]
    distribution = {"90-100": 0, "80-89": 0, "70-79": 0, "60-69": 0, "0-59": 0}
    for s in scores:
        if s >= 90:
            distribution["90-100"] += 1
        elif s >= 80:
            distribution["80-89"] += 1
        elif s >= 70:
            distribution["70-79"] += 1
        elif s >= 60:
            distribution["60-69"] += 1
        else:
            distribution["0-59"] += 1

    passed = sum(1 for g in grades if g.is_pass)
    return {
        "code": "OK",
        "message": "success",
        "data": {
            "course_name": course.name,
            "total": len(grades),
            "average": round(sum(scores) / len(scores), 2),
            "max_score": max(scores),
            "min_score": min(scores),
            "pass_rate": round(passed / len(grades) * 100, 1),
            "distribution": distribution,
        },
    }


@router.get("/stats/class-rank", response_model=Resp[list[dict]], summary="管理端：班级成绩排名")
def class_rank(db: DbSession, _: TeacherUser, class_id: int = Query(...)):
    students = db.execute(select(Student).where(Student.class_id == class_id)).scalars().all()
    rows = []
    for s in students:
        stat = grade_service.gpa_stat(db, s)
        rows.append({
            "student_id": s.id,
            "student_no": s.student_no,
            "student_name": s.name,
            "gpa": stat["overall_gpa"],
            "earned_credits": stat["total_credits_earned"],
            "failed_count": stat["failed_course_count"],
        })
    rows.sort(key=lambda x: x["gpa"], reverse=True)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return {"code": "OK", "message": "success", "data": rows}
