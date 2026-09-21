"""成绩与 GPA 服务。

绩点换算采用国内高校常见的 4.0 分制分段映射（可在 GRADE_POINT_TABLE 里调整）：
    >=90 -> 4.0 | 85-89 -> 3.7 | 82-84 -> 3.3 | 78-81 -> 3.0 | 75-77 -> 2.7
    72-74 -> 2.3 | 68-71 -> 2.0 | 64-67 -> 1.5 | 60-63 -> 1.0 | <60 -> 0

GPA 采用**学分加权平均**而不是简单算术平均：3 学分的专业课和 1 学分的通识课
对绩点的影响必须区分权重，否则会影响保研/评奖的公平性。
重修课程只取通过的那次计入 GPA（见 build_academic_state 的去重逻辑）。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.exceptions import BizError, NotFoundError
from app.models.course import Course
from app.models.enrollment import Enrollment, Grade
from app.models.enums import CourseType, EnrollmentStatus
from app.models.teaching import Semester
from app.models.user import Student

GRADE_POINT_TABLE: list[tuple[int, float]] = [
    (90, 4.0), (85, 3.7), (82, 3.3), (78, 3.0), (75, 2.7),
    (72, 2.3), (68, 2.0), (64, 1.5), (60, 1.0), (0, 0.0),
]


def score_to_grade_point(score: float) -> float:
    for threshold, point in GRADE_POINT_TABLE:
        if score >= threshold:
            return point
    return 0.0


def compute_final_score(
    usual_score: float | None,
    exam_score: float | None,
    usual_weight: float = 0.4,
) -> float:
    """总评成绩：只录入了一项就按该项计，两项都有则按权重加权。"""
    if usual_score is not None and exam_score is not None:
        return round(usual_score * usual_weight + exam_score * (1 - usual_weight), 1)
    if exam_score is not None:
        return round(exam_score, 1)
    if usual_score is not None:
        return round(usual_score, 1)
    raise BizError("平时成绩与期末成绩至少需要录入一项")


def record_grade(
    db: Session,
    *,
    enrollment_id: int,
    usual_score: float | None,
    exam_score: float | None,
    final_score: float | None,
    usual_weight: float,
    recorder_id: int | None,
    remark: str | None = None,
) -> Grade:
    enrollment = db.execute(
        select(Enrollment)
        .options(selectinload(Enrollment.course), selectinload(Enrollment.grade))
        .where(Enrollment.id == enrollment_id)
    ).scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("选课记录不存在")
    if enrollment.status == EnrollmentStatus.DROPPED:
        raise BizError("该选课记录已退课，无法录入成绩", code="ENROLLMENT_DROPPED")

    total = final_score if final_score is not None else compute_final_score(usual_score, exam_score, usual_weight)
    if not 0 <= total <= 100:
        raise BizError("总评成绩必须在 0-100 之间")

    course = enrollment.course
    is_pass = total >= settings.PASS_SCORE

    # 同一门课历史修读次数 + 1，用于标记第几次修读
    attempt_no = db.execute(
        select(func.count(Grade.id)).where(
            Grade.student_id == enrollment.student_id,
            Grade.course_id == enrollment.course_id,
        )
    ).scalar_one() + 1

    grade = enrollment.grade
    if grade is None:
        grade = Grade(enrollment_id=enrollment.id, student_id=enrollment.student_id,
                      course_id=enrollment.course_id, semester_id=enrollment.semester_id)
        db.add(grade)

    grade.usual_score = usual_score
    grade.exam_score = exam_score
    grade.final_score = total
    grade.grade_point = score_to_grade_point(total)
    grade.credits = course.credits if course else enrollment.credits
    grade.is_pass = is_pass
    grade.is_retake = attempt_no > 1
    grade.attempt_no = attempt_no
    grade.recorder_id = recorder_id
    grade.remark = remark

    # 出成绩即视为完成修读
    enrollment.status = EnrollmentStatus.COMPLETED
    db.commit()
    db.refresh(grade)
    return grade


def list_student_grades(
    db: Session,
    student_id: int,
    semester_id: int | None = None,
    course_type: CourseType | None = None,
) -> list[Grade]:
    stmt = (
        select(Grade)
        .options(selectinload(Grade.course))
        .where(Grade.student_id == student_id)
        .order_by(Grade.semester_id.desc(), Grade.id.desc())
    )
    if semester_id:
        stmt = stmt.where(Grade.semester_id == semester_id)
    if course_type:
        stmt = stmt.join(Course, Course.id == Grade.course_id).where(Course.course_type == course_type)
    return list(db.execute(stmt).scalars().all())


def gpa_stat(db: Session, student: Student, semester_id: int | None = None) -> dict:
    """总览统计：累计 GPA、已获学分、通过/挂科门数、班级排名、逐学期趋势。"""
    grades = list(db.execute(
        select(Grade).options(selectinload(Grade.course)).where(Grade.student_id == student.id)
    ).scalars().all())

    total_point, total_credit = 0.0, 0.0
    earned, attempted = 0.0, 0.0
    passed_count, failed_count = 0, 0
    counted: set[int] = set()
    by_semester: dict[int, dict] = {}

    semester_map = {s.id: s for s in db.execute(select(Semester)).scalars().all()}
    for g in grades:
        bucket = by_semester.setdefault(
            g.semester_id,
            {"semester_id": g.semester_id,
             "semester_name": semester_map[g.semester_id].name if g.semester_id in semester_map else "",
             "credits": 0.0, "point_sum": 0.0, "gpa": 0.0, "course_count": 0, "passed": 0},
        )
        bucket["credits"] += g.credits
        bucket["point_sum"] += g.grade_point * g.credits
        bucket["course_count"] += 1

        if g.is_pass:
            passed_count += 1
            bucket["passed"] += 1
            if g.course_id not in counted:
                counted.add(g.course_id)
                earned += g.credits
                total_point += g.grade_point * g.credits
                total_credit += g.credits
        else:
            failed_count += 1
        attempted += g.credits

    for bucket in by_semester.values():
        bucket["gpa"] = round(bucket.pop("point_sum") / bucket["credits"], 3) if bucket["credits"] else 0.0

    overall_gpa = round(total_point / total_credit, 3) if total_credit else 0.0

    # 班级排名：同班同学按 GPA 排序，注意"并列同名次"的处理
    rank, class_size = None, None
    if student.class_id:
        class_students = list(db.execute(
            select(Student).where(Student.class_id == student.class_id, Student.status == "ENROLLED")
        ).scalars().all())
        gpa_list = []
        for s in class_students:
            row = db.execute(
                select(func.sum(Grade.grade_point * Grade.credits), func.sum(Grade.credits))
                .where(Grade.student_id == s.id, Grade.is_pass.is_(True))
            ).one()
            point_sum, credit_sum = row[0] or 0.0, row[1] or 0.0
            gpa_list.append((s.id, round(point_sum / credit_sum, 3) if credit_sum else 0.0))
        gpa_list.sort(key=lambda x: x[1], reverse=True)
        class_size = len(gpa_list)
        rank = next((i + 1 for i, (sid, _) in enumerate(gpa_list) if sid == student.id), None)

    return {
        "overall_gpa": overall_gpa,
        "total_credits_earned": round(earned, 1),
        "total_credits_attempted": round(attempted, 1),
        "passed_course_count": passed_count,
        "failed_course_count": failed_count,
        "rank_in_class": rank,
        "class_size": class_size,
        "by_semester": sorted(by_semester.values(), key=lambda x: x["semester_id"]),
    }


def failed_courses(db: Session, student_id: int) -> list[Grade]:
    """挂科清单：同一门课多次不及格只保留最后一次，用于重修提醒。"""
    grades = list(db.execute(
        select(Grade).options(selectinload(Grade.course))
        .where(Grade.student_id == student_id, Grade.is_pass.is_(False))
        .order_by(Grade.course_id, Grade.attempt_no)
    ).scalars().all())
    latest: dict[int, Grade] = {}
    for g in grades:
        latest[g.course_id] = g
    return list(latest.values())
