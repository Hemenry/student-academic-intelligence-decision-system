"""毕业进度分析：回答"我离毕业还差什么"。

三类核心输出：
1. 学分完成度：按课程类别（专业必修/专业选修/公共必修/通识选修）拆分培养方案要求与实际已得学分；
2. 缺口清单：培养方案里还没通过的必修课（按学期顺序排列，指导学生下一步选课）；
3. 状态研判：结合剩余学期与修读速度，给出"按期毕业 / 需加速 / 存在延期风险"的结论。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.course import Course
from app.models.enrollment import Enrollment, Grade
from app.models.enums import CourseType, StudentStatus
from app.models.org import Major
from app.models.rule import GraduationRequirement
from app.models.teaching import Semester
from app.models.user import Student
from app.services.grade_service import gpa_stat

TYPE_LABELS: dict[CourseType, str] = {
    CourseType.REQUIRED: "专业必修",
    CourseType.ELECTIVE: "专业选修",
    CourseType.PUBLIC: "公共必修",
    CourseType.GENERAL: "通识选修",
}


def graduation_progress(db: Session, student: Student) -> dict:
    major: Major | None = db.get(Major, student.major_id)
    required_total = float(major.total_credits) if major else 160.0

    requirements = list(db.execute(
        select(GraduationRequirement).where(GraduationRequirement.major_id == student.major_id)
    ).scalars().all())

    # 已通过课程（同一门课重修只计一次）
    grade_rows = db.execute(
        select(Grade).options(selectinload(Grade.course)).where(
            Grade.student_id == student.id, Grade.is_pass.is_(True)
        ).order_by(Grade.semester_id)
    ).scalars().all()

    earned_by_type: dict[CourseType, float] = {t: 0.0 for t in CourseType}
    earned_ids: set[int] = set()
    for g in grade_rows:
        if g.course_id in earned_ids or g.course is None:
            continue
        earned_ids.add(g.course_id)
        earned_by_type[g.course.course_type] += g.credits

    earned_total = sum(earned_by_type.values())

    by_type = []
    for req in requirements:
        earned = earned_by_type.get(req.course_type, 0.0)
        by_type.append({
            "course_type": req.course_type.value,
            "label": TYPE_LABELS.get(req.course_type, req.course_type.value),
            "required_credits": req.min_credits,
            "earned_credits": round(earned, 1),
            "gap": round(max(req.min_credits - earned, 0), 1),
            "percent": round(min(earned / req.min_credits * 100, 100), 1) if req.min_credits else 100.0,
        })

    # 缺口中未通过/未修读的专业必修课
    missing = _missing_required_courses(db, student, earned_ids)

    # 修读速度研判
    current = db.execute(select(Semester).where(Semester.is_current.is_(True))).scalar_one_or_none()
    semester_index = 1
    if current:
        semester_index = max((current.start_date.year - student.enrollment_year) * 2 + current.term, 1)
    completed = max(semester_index - 1, 0)
    remaining_semesters = max(8 - semester_index, 0)
    needed = max(required_total - earned_total, 0)
    # 与学生自身修读速度对齐：低年级样本太少，不做外推，只提示"修读中"
    pace = earned_total / completed if completed else 0.0
    projected = earned_total + pace * remaining_semesters

    if student.status == StudentStatus.GRADUATED:
        estimated, suggestion = "已毕业", "学业已完成，祝前程似锦。"
    elif needed <= 0:
        estimated = "学分已达标"
        suggestion = "学分要求已满足，请核对毕业论文/实践环节等非学分要求。"
    elif completed < 3:
        estimated = "修读中"
        suggestion = (
            f"当前处于第 {semester_index} 个学期，已完成 {earned_total:g} 学分；"
            f"按培养方案节奏推进即可，暂无进度风险。"
        )
    elif remaining_semesters <= 0:
        estimated = "存在延期风险"
        suggestion = "已超出标准学制，建议尽快申请延长学习年限并制定补修计划。"
    elif projected < required_total * 0.9:
        estimated = "需加速修读"
        suggestion = (
            f"已完成 {completed} 个学期，平均每学期 {pace:.1f} 学分，"
            f"按此速度外推毕业时约 {projected:.1f} 学分（要求 {required_total:g}）；"
            f"建议后续每学期提高到 {max(needed / max(remaining_semesters, 1), 0):.1f} 学分以上。"
        )
    else:
        estimated = "预计按期毕业"
        suggestion = (
            f"剩余 {needed:g} 学分、{remaining_semesters} 个学期，"
            f"平均每学期修读 {needed / max(remaining_semesters, 1):.1f} 学分即可达标。"
        )

    stat = gpa_stat(db, student)

    return {
        "major_name": major.name if major else "",
        "required_total": required_total,
        "earned_total": round(earned_total, 1),
        "progress_percent": round(min(earned_total / required_total * 100, 100), 1) if required_total else 0.0,
        "by_type": by_type,
        "missing_required_courses": missing,
        "estimated_status": estimated,
        "suggestion": suggestion,
        "gpa": stat["overall_gpa"],
        "semester_index": semester_index,
    }


def _missing_required_courses(db: Session, student: Student, earned_ids: set[int], limit: int = 20) -> list[dict]:
    """培养方案内、属于本专业必修、且学生尚未通过的课程。"""
    scope_key = str(student.major_id)
    courses = list(db.execute(
        select(Course).where(Course.course_type == CourseType.REQUIRED, Course.is_active.is_(True))
    ).scalars().all())

    missing = []
    for c in courses:
        # major_scope 为空视为全校必修；否则需包含本专业
        if c.major_scope:
            scopes = {s.strip() for s in c.major_scope.split(",") if s.strip()}
            if scope_key not in scopes:
                continue
        if c.id in earned_ids:
            continue
        # 是否已选未出成绩
        in_progress = db.execute(
            select(Enrollment.id).where(
                Enrollment.student_id == student.id,
                Enrollment.course_id == c.id,
                Enrollment.status != "DROPPED",
            ).limit(1)
        ).scalar_one_or_none() is not None
        missing.append({
            "course_id": c.id,
            "course_code": c.code,
            "course_name": c.name,
            "credits": c.credits,
            "status": "修读中" if in_progress else "未修读",
        })

    missing.sort(key=lambda x: (x["status"] != "未修读", x["course_code"]))
    return missing[:limit]


def class_statistics(db: Session) -> dict:
    """管理端看板：学院/专业维度的选课与成绩概览。"""
    from sqlalchemy import func

    from app.models.course import Course as C
    from app.models.enums import EnrollmentStatus as ES
    from app.models.teaching import CourseOffering as CO

    student_count = db.execute(select(func.count(Student.id))).scalar_one()
    course_count = db.execute(select(func.count(C.id))).scalar_one()
    offering_count = db.execute(select(func.count(CO.id))).scalar_one()
    enrollment_count = db.execute(
        select(func.count(Enrollment.id)).where(Enrollment.status != ES.DROPPED)
    ).scalar_one()
    avg_row = db.execute(select(func.avg(Grade.final_score), func.count(Grade.id))).one()

    return {
        "student_count": student_count,
        "course_count": course_count,
        "offering_count": offering_count,
        "enrollment_count": enrollment_count,
        "graded_count": avg_row[1] or 0,
        "average_score": round(float(avg_row[0]), 2) if avg_row[0] is not None else 0.0,
    }
