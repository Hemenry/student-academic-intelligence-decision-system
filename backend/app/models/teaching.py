"""教学运行模型：学期（Semester）、开课计划/教学班（CourseOffering）、上课时间段（OfferingTimeSlot）。

其中 CourseOffering.selected_count 是**选课人数计数器**，也是并发扣减的争用热点：
选课事务里对这条记录加行锁（SELECT ... FOR UPDATE）后 read-modify-write，保证不超卖。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
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
from app.models.enums import SemesterStatus

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import Teacher


class Semester(Base, PKMixin, TimestampMixin):
    __tablename__ = "t_semester"

    code: Mapped[str] = mapped_column(String(24), unique=True, index=True, comment="如 2025-2026-1")
    name: Mapped[str] = mapped_column(String(48), comment="如 2025-2026学年第一学期")
    academic_year: Mapped[str] = mapped_column(String(16), comment="如 2025-2026")
    term: Mapped[int] = mapped_column(Integer, comment="1=秋季 2=春季")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # 选课窗口：规则引擎据此判断"是否在选课时间内"，无需管理员手工开关
    select_start_at: Mapped[datetime | None] = mapped_column(DateTime)
    select_end_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[SemesterStatus] = mapped_column(
        SAEnum(SemesterStatus, native_enum=False, length=16), default=SemesterStatus.PLANNING, index=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True, comment="当前学期唯一")


class CourseOffering(Base, PKMixin, TimestampMixin):
    """教学班（开课计划）：课程 + 学期 + 教师 + 容量 + 时间地点的组合。"""

    __tablename__ = "t_course_offering"
    __table_args__ = (
        Index("idx_offering_semester_course", "semester_id", "course_id"),
    )

    course_id: Mapped[int] = mapped_column(ForeignKey("t_course.id"), index=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("t_semester.id"), index=True)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("t_teacher.id"), index=True)
    class_name: Mapped[str] = mapped_column(String(64), default="01班", comment="教学班名称")

    capacity: Mapped[int] = mapped_column(Integer, default=60, comment="课容量")
    selected_count: Mapped[int] = mapped_column(Integer, default=0, comment="已选人数（行锁保护）")
    credit_limit: Mapped[float | None] = mapped_column(Float, comment="单班学分上限，空则用学期默认")

    campus: Mapped[str] = mapped_column(String(32), default="主校区")
    classroom: Mapped[str] = mapped_column(String(64), default="待定")
    # 面向专业（空=全校可选），选课规则会校验专业是否匹配
    major_scope: Mapped[str | None] = mapped_column(String(255), comment="面向专业ID，逗号分隔，空=全校")
    grade_scope: Mapped[str | None] = mapped_column(String(64), comment="面向年级，逗号分隔，空=不限")
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否开放选课")
    remark: Mapped[str | None] = mapped_column(String(255))

    course: Mapped["Course"] = relationship()
    semester: Mapped["Semester"] = relationship()
    teacher: Mapped["Teacher | None"] = relationship()
    time_slots: Mapped[list["OfferingTimeSlot"]] = relationship(
        back_populates="offering", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def remaining(self) -> int:
        return max(self.capacity - self.selected_count, 0)


class OfferingTimeSlot(Base, PKMixin, TimestampMixin):
    """上课时间段：周几 + 第几节到第几节 + 周次区间。时间冲突检测的最小粒度。"""

    __tablename__ = "t_offering_time_slot"
    __table_args__ = (
        Index("idx_slot_weekday_section", "weekday", "start_section", "end_section"),
    )

    offering_id: Mapped[int] = mapped_column(ForeignKey("t_course_offering.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer, comment="1=周一 ... 7=周日")
    start_section: Mapped[int] = mapped_column(Integer, comment="起始节次，如 1")
    end_section: Mapped[int] = mapped_column(Integer, comment="结束节次，如 2")
    start_week: Mapped[int] = mapped_column(Integer, default=1)
    end_week: Mapped[int] = mapped_column(Integer, default=16)
    weeks_desc: Mapped[str | None] = mapped_column(String(64), comment="如 1-16周")

    offering: Mapped["CourseOffering"] = relationship(back_populates="time_slots")
