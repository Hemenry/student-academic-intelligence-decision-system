"""组织架构模型：专业（Major）与班级（ClassGroup）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import Student


class Major(Base, PKMixin, TimestampMixin):
    """专业。毕业总学分要求挂在专业上，毕业进度分析以此为基准。"""

    __tablename__ = "t_major"

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="专业代码")
    name: Mapped[str] = mapped_column(String(64), index=True, comment="专业名称")
    college: Mapped[str] = mapped_column(String(64), comment="所属学院")
    duration_years: Mapped[int] = mapped_column(Integer, default=4, comment="学制（年）")
    total_credits: Mapped[int] = mapped_column(Integer, default=160, comment="毕业总学分要求")
    degree: Mapped[str] = mapped_column(String(32), default="工学学士", comment="授予学位")

    classes: Mapped[list["ClassGroup"]] = relationship(back_populates="major", cascade="all, delete-orphan")


class ClassGroup(Base, PKMixin, TimestampMixin):
    """班级。一个专业下按入学年级划分若干行政班。"""

    __tablename__ = "t_class_group"

    name: Mapped[str] = mapped_column(String(64), comment="班级名称，如 计算机2301")
    major_id: Mapped[int] = mapped_column(ForeignKey("t_major.id", ondelete="CASCADE"), index=True)
    grade_year: Mapped[int] = mapped_column(Integer, comment="入学年份")
    counselor: Mapped[str | None] = mapped_column(String(32), comment="辅导员")
    remark: Mapped[str | None] = mapped_column(String(255))

    major: Mapped["Major"] = relationship(back_populates="classes")
    students: Mapped[list["Student"]] = relationship(back_populates="class_group")
