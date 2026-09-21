"""领域枚举：用字符串枚举落库，可读性好、排查线上数据方便。"""
from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"      # 教务管理员
    TEACHER = "TEACHER"  # 教师
    STUDENT = "STUDENT"  # 学生


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class StudentStatus(StrEnum):
    ENROLLED = "ENROLLED"  # 在读
    SUSPENDED = "SUSPENDED"  # 休学
    GRADUATED = "GRADUATED"  # 已毕业
    DROPPED = "DROPPED"  # 退学


class CourseType(StrEnum):
    REQUIRED = "REQUIRED"  # 专业必修
    ELECTIVE = "ELECTIVE"  # 专业选修
    PUBLIC = "PUBLIC"      # 公共必修（英语/体育等）
    GENERAL = "GENERAL"    # 通识选修


class SemesterStatus(StrEnum):
    PLANNING = "PLANNING"    # 计划中，未开放选课
    SELECTING = "SELECTING"  # 选课进行中
    ONGOING = "ONGOING"      # 学期进行中
    FINISHED = "FINISHED"    # 已结束（成绩归档）


class EnrollmentStatus(StrEnum):
    SELECTED = "SELECTED"  # 已选
    DROPPED = "DROPPED"    # 已退
    COMPLETED = "COMPLETED"  # 已出成绩


class EnrollType(StrEnum):
    NORMAL = "NORMAL"    # 正常修读
    RETAKE = "RETAKE"    # 重修
    MAKEUP = "MAKEUP"    # 补修


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskType(StrEnum):
    FAILED_COURSE = "FAILED_COURSE"        # 挂科风险
    GPA_WARNING = "GPA_WARNING"            # 绩点预警
    CREDIT_LAG = "CREDIT_LAG"              # 学分进度落后
    GRADUATION_RISK = "GRADUATION_RISK"    # 毕业风险
    TREND_DOWN = "TREND_DOWN"              # 成绩下滑趋势


class AlertStatus(StrEnum):
    OPEN = "OPEN"
    HANDLED = "HANDLED"
    IGNORED = "IGNORED"
