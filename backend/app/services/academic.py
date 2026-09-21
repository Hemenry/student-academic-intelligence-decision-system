"""学业状态快照：把"判断一门课能不能选"需要的数据一次性装配好。

为什么单独抽这一层：
选课校验要读本学期已选课程、时间占用、历史成绩、GPA 等一堆数据。
如果每条规则各自查库，一次选课就是 N 次 SQL（典型的 N+1 问题）。
这里统一做一次装配，规则只读内存快照，既减少 DB 往返，也让规则本身变成纯函数、便于单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.course import Course
from app.models.enrollment import Enrollment, Grade
from app.models.enums import EnrollmentStatus
from app.models.teaching import CourseOffering, OfferingTimeSlot, Semester
from app.models.user import Student


@dataclass
class TimeBlock:
    weekday: int
    start_section: int
    end_section: int
    start_week: int
    end_week: int
    source: str = ""  # 占用来源：课程名

    def conflicts_with(self, other: "TimeBlock") -> bool:
        """同一天 + 节次区间重叠 + 周次区间重叠 => 冲突。"""
        if self.weekday != other.weekday:
            return False
        section_overlap = not (self.end_section < other.start_section or other.end_section < self.start_section)
        week_overlap = not (self.end_week < other.start_week or other.end_week < self.start_week)
        return section_overlap and week_overlap


@dataclass
class AcademicState:
    """某个学生在某个学期的完整学业快照。"""

    student: Student
    semester: Semester | None
    enrollments: list[Enrollment] = field(default_factory=list)
    time_blocks: list[TimeBlock] = field(default_factory=list)
    # course_id -> 最好成绩（含不及格），用于先修课判断
    best_score: dict[int, float] = field(default_factory=dict)
    # 已通过（>=60）的课程 id
    passed_course_ids: set[int] = field(default_factory=set)
    # 本学期已选（含已出成绩）的课程 id
    selected_course_ids: set[int] = field(default_factory=set)
    current_credits: float = 0.0
    overall_gpa: float = 0.0
    earned_credits: float = 0.0
    failed_count: int = 0

    @property
    def max_credits(self) -> float:
        return float(settings.DEFAULT_MAX_CREDITS_PER_SEMESTER)


def build_academic_state(db: Session, student: Student, semester: Semester | None) -> AcademicState:
    state = AcademicState(student=student, semester=semester)

    # ---------- 历史成绩：一次查全，内存里算 ----------
    grade_rows = db.execute(
        select(Grade).where(Grade.student_id == student.id)
    ).scalars().all()

    total_point, total_credit = 0.0, 0.0
    counted_course: set[int] = set()
    for g in grade_rows:
        prev = state.best_score.get(g.course_id)
        if prev is None or g.final_score > prev:
            state.best_score[g.course_id] = g.final_score
        if g.is_pass:
            state.passed_course_ids.add(g.course_id)
            # 同一门课重修通过只计一次学分与绩点，避免刷学分
            if g.course_id not in counted_course:
                counted_course.add(g.course_id)
                state.earned_credits += g.credits
                total_point += g.grade_point * g.credits
                total_credit += g.credits
        else:
            state.failed_count += 1

    state.overall_gpa = round(total_point / total_credit, 3) if total_credit else 0.0

    # ---------- 本学期已选课程 + 时间占用 ----------
    if semester is not None:
        enrollments = db.execute(
            select(Enrollment)
            .options(
                selectinload(Enrollment.course),
                selectinload(Enrollment.offering).selectinload(CourseOffering.time_slots),
            )
            .where(
                Enrollment.student_id == student.id,
                Enrollment.semester_id == semester.id,
                Enrollment.status != EnrollmentStatus.DROPPED,
            )
        ).scalars().all()

        state.enrollments = list(enrollments)
        for en in enrollments:
            state.selected_course_ids.add(en.course_id)
            state.current_credits += en.credits
            course_name = en.course.name if en.course else f"课程{en.course_id}"
            for slot in (en.offering.time_slots if en.offering else []):
                state.time_blocks.append(
                    TimeBlock(
                        weekday=slot.weekday,
                        start_section=slot.start_section,
                        end_section=slot.end_section,
                        start_week=slot.start_week,
                        end_week=slot.end_week,
                        source=course_name,
                    )
                )

    return state


def offering_time_blocks(offering: CourseOffering, course_name: str = "") -> list[TimeBlock]:
    return [
        TimeBlock(
            weekday=s.weekday,
            start_section=s.start_section,
            end_section=s.end_section,
            start_week=s.start_week,
            end_week=s.end_week,
            source=course_name,
        )
        for s in offering.time_slots
    ]


def load_offering(db: Session, offering_id: int) -> CourseOffering | None:
    return db.execute(
        select(CourseOffering)
        .options(
            selectinload(CourseOffering.time_slots),
            selectinload(CourseOffering.course),
            selectinload(CourseOffering.semester),
        )
        .where(CourseOffering.id == offering_id)
    ).scalar_one_or_none()


def load_course(db: Session, course_id: int) -> Course | None:
    return db.get(Course, course_id)


def sections_to_text(slot: OfferingTimeSlot) -> str:
    return f"周{'一二三四五六日'[slot.weekday - 1]}第{slot.start_section}-{slot.end_section}节"
