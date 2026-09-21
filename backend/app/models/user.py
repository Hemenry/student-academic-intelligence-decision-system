"""用户体系：一张 sys_user 承载登录凭证，学生/教师档案通过外键扩展。

这样设计的好处：登录鉴权只查一张表，学生与教师共享认证逻辑；
角色（role）决定数据权限范围，避免为每个角色建一套登录体系。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SAEnum

from app.db.base import Base, PKMixin, TimestampMixin
from app.models.enums import StudentStatus, UserRole, UserStatus

if TYPE_CHECKING:
    from app.models.org import ClassGroup, Major


class SysUser(Base, PKMixin, TimestampMixin):
    __tablename__ = "t_sys_user"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="登录账号（学号/工号）")
    password_hash: Mapped[str] = mapped_column(String(128), comment="bcrypt 哈希，禁止存明文")
    real_name: Mapped[str] = mapped_column(String(32))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole, native_enum=False, length=16), index=True)
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, native_enum=False, length=16), default=UserStatus.ACTIVE
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最后登录时间")

    student: Mapped["Student | None"] = relationship(back_populates="user", uselist=False)
    teacher: Mapped["Teacher | None"] = relationship(back_populates="user", uselist=False)


class Student(Base, PKMixin, TimestampMixin):
    __tablename__ = "t_student"

    user_id: Mapped[int] = mapped_column(ForeignKey("t_sys_user.id", ondelete="CASCADE"), unique=True)
    student_no: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="学号")
    name: Mapped[str] = mapped_column(String(32))
    gender: Mapped[str] = mapped_column(String(8), default="M")
    major_id: Mapped[int] = mapped_column(ForeignKey("t_major.id"), index=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("t_class_group.id"), index=True)
    enrollment_year: Mapped[int] = mapped_column(Integer, comment="入学年份")
    status: Mapped[StudentStatus] = mapped_column(
        SAEnum(StudentStatus, native_enum=False, length=16), default=StudentStatus.ENROLLED
    )
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(64))

    user: Mapped["SysUser"] = relationship(back_populates="student")
    major: Mapped["Major"] = relationship()
    class_group: Mapped["ClassGroup | None"] = relationship(back_populates="students")


class Teacher(Base, PKMixin, TimestampMixin):
    __tablename__ = "t_teacher"

    user_id: Mapped[int] = mapped_column(ForeignKey("t_sys_user.id", ondelete="CASCADE"), unique=True)
    teacher_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(32), default="讲师", comment="职称")
    college: Mapped[str] = mapped_column(String(64))

    user: Mapped["SysUser"] = relationship(back_populates="teacher")
