"""集中导出所有 ORM 模型，保证 Base.metadata 在 create_all 前已注册全部表。"""
from app.db.base import Base
from app.models.course import Course, CoursePrerequisite
from app.models.enrollment import Enrollment, Grade
from app.models.enums import (
    AlertStatus,
    CourseType,
    EnrollType,
    EnrollmentStatus,
    RiskLevel,
    RiskType,
    SemesterStatus,
    StudentStatus,
    UserRole,
    UserStatus,
)
from app.models.org import ClassGroup, Major
from app.models.risk import RiskAlert
from app.models.rule import GraduationRequirement, SelectRule
from app.models.teaching import CourseOffering, OfferingTimeSlot, Semester
from app.models.user import Student, SysUser, Teacher

__all__ = [
    "Base",
    "SysUser",
    "Student",
    "Teacher",
    "Major",
    "ClassGroup",
    "Course",
    "CoursePrerequisite",
    "Semester",
    "CourseOffering",
    "OfferingTimeSlot",
    "Enrollment",
    "Grade",
    "SelectRule",
    "GraduationRequirement",
    "RiskAlert",
    # enums
    "UserRole",
    "UserStatus",
    "StudentStatus",
    "CourseType",
    "SemesterStatus",
    "EnrollmentStatus",
    "EnrollType",
    "RiskLevel",
    "RiskType",
    "AlertStatus",
]
