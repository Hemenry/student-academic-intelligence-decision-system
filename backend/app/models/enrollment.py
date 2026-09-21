"""选课与成绩模型。

设计要点（面试可展开）：
1. t_enrollment 冗余了 course_id / semester_id —— 一是为了建
   (student_id, course_id, semester_id) 唯一约束，从数据库层面兜底"同课重复选"；
   二是让"某学期学了哪些课""这门课历史通过率"这类统计免去多表 JOIN。
2. 成绩独立成 t_grade，与选课记录 1:1（enrollment_id 唯一）：
   选课是过程数据、成绩是结果数据，分开后重修不会覆盖历史成绩，
   attempt_no 记录第几次修读，GPA 计算只取通过的那次。
3. drop 采用软删除（status=DROPPED），保留选课/退课流水，便于审计与反查恶意刷课。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SAEnum

from app.db.base import Base, PKMixin, TimestampMixin
from app.models.enums import EnrollmentStatus, EnrollType

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.teaching import CourseOffering


class Enrollment(Base, PKMixin, TimestampMixin):
    __tablename__ = "t_enrollment"
    __table_args__ = (
        # 同一学生、同一门课、同一学期只能有一条选课记录（退课后重新选会复用该行）
        UniqueConstraint("student_id", "course_id", "semester_id", name="uk_student_course_semester"),
        Index("idx_enroll_student_semester", "student_id", "semester_id"),
        Index("idx_enroll_offering", "offering_id", "status"),
    )

    student_id: Mapped[int] = mapped_column(ForeignKey("t_student.id", ondelete="CASCADE"), index=True)
    offering_id: Mapped[int] = mapped_column(ForeignKey("t_course_offering.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("t_course.id"), index=True, comment="冗余字段")
    semester_id: Mapped[int] = mapped_column(ForeignKey("t_semester.id"), index=True, comment="冗余字段")

    status: Mapped[EnrollmentStatus] = mapped_column(
        SAEnum(EnrollmentStatus, native_enum=False, length=16), default=EnrollmentStatus.SELECTED, index=True
    )
    enroll_type: Mapped[EnrollType] = mapped_column(
        SAEnum(EnrollType, native_enum=False, length=16), default=EnrollType.NORMAL
    )
    credits: Mapped[float] = mapped_column(Float, default=0, comment="选课时快照学分，防止课程学分变更影响历史统计")
    select_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    drop_at: Mapped[datetime | None] = mapped_column(DateTime)
    drop_reason: Mapped[str | None] = mapped_column(String(128))

    offering: Mapped["CourseOffering"] = relationship()
    course: Mapped["Course"] = relationship()
    grade: Mapped["Grade | None"] = relationship(back_populates="enrollment", uselist=False)


class Grade(Base, PKMixin, TimestampMixin):
    """成绩单：总评 = 平时成绩 * w1 + 期末成绩 * w2（权重可在录入时指定）。"""

    __tablename__ = "t_grade"
    __table_args__ = (
        Index("idx_grade_student_semester", "student_id", "semester_id"),
    )

    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("t_enrollment.id", ondelete="CASCADE"), unique=True, comment="一条选课记录对应一份成绩"
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("t_student.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("t_course.id"), index=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("t_semester.id"), index=True)

    attempt_no: Mapped[int] = mapped_column(Integer, default=1, comment="第几次修读，重修递增")
    usual_score: Mapped[float | None] = mapped_column(Float, comment="平时成绩")
    exam_score: Mapped[float | None] = mapped_column(Float, comment="期末成绩")
    final_score: Mapped[float] = mapped_column(Float, comment="总评成绩")
    grade_point: Mapped[float] = mapped_column(Float, default=0, comment="绩点（4.0 制）")
    credits: Mapped[float] = mapped_column(Float, default=0, comment="学分快照")
    is_pass: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否及格")
    is_retake: Mapped[bool] = mapped_column(Boolean, default=False)
    recorder_id: Mapped[int | None] = mapped_column(ForeignKey("t_sys_user.id"), comment="录入人")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    remark: Mapped[str | None] = mapped_column(String(255))

    enrollment: Mapped["Enrollment"] = relationship(back_populates="grade")
    course: Mapped["Course"] = relationship()
