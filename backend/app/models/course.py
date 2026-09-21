"""课程库模型：课程本体 + 先修课依赖关系。

课程（Course）是"教学大纲层面的课"，一学期可开出多个教学班（CourseOffering）；
先修关系单独建表，是为了支持一门课有多个先修课、且可配置最低分数要求。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SAEnum

from app.db.base import Base, PKMixin, TimestampMixin
from app.models.enums import CourseType

if TYPE_CHECKING:
    pass


class Course(Base, PKMixin, TimestampMixin):
    __tablename__ = "t_course"

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="课程代码")
    name: Mapped[str] = mapped_column(String(64), index=True, comment="课程名称")
    credits: Mapped[float] = mapped_column(comment="学分")
    hours: Mapped[int] = mapped_column(Integer, default=48, comment="总学时")
    course_type: Mapped[CourseType] = mapped_column(
        SAEnum(CourseType, native_enum=False, length=16), index=True, comment="课程类别"
    )
    college: Mapped[str] = mapped_column(String(64), default="", comment="开课学院")
    # 适用专业：为空表示全校通识；否则存逗号分隔的专业 id，便于规则引擎校验专业匹配度
    major_scope: Mapped[str | None] = mapped_column(String(255), comment="适用专业ID，逗号分隔，空=全校")
    description: Mapped[str | None] = mapped_column(Text, comment="课程简介/推荐语素材")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 注意命名：这里叫 prereq_links 而不是 prerequisites，
    # 是为了避免与 API 响应模型 CourseOut.prerequisites（结构化出参）同名，
    # 否则 Pydantic 的 from_attributes 会把 ORM 对象直接塞进 response_model 导致校验失败
    prereq_links: Mapped[list["CoursePrerequisite"]] = relationship(
        back_populates="course",
        foreign_keys="CoursePrerequisite.course_id",
        cascade="all, delete-orphan",
    )


class CoursePrerequisite(Base, PKMixin, TimestampMixin):
    """先修课配置：(course_id) 要求先修完 (prerequisite_course_id) 且分数 >= min_score。"""

    __tablename__ = "t_course_prerequisite"
    __table_args__ = (UniqueConstraint("course_id", "prerequisite_course_id", name="uk_course_prereq"),)

    course_id: Mapped[int] = mapped_column(ForeignKey("t_course.id", ondelete="CASCADE"), index=True)
    prerequisite_course_id: Mapped[int] = mapped_column(ForeignKey("t_course.id", ondelete="CASCADE"), index=True)
    min_score: Mapped[int] = mapped_column(Integer, default=60, comment="先修课最低分数")
    # 允许"先修课在修"（同修），部分高校允许
    allow_concurrent: Mapped[bool] = mapped_column(Boolean, default=False)

    course: Mapped["Course"] = relationship(back_populates="prereq_links", foreign_keys=[course_id])
    prerequisite: Mapped["Course"] = relationship(foreign_keys=[prerequisite_course_id])
