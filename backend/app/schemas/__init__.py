"""Pydantic 入参/出参模型：接口契约的单一事实来源，同时驱动 Swagger 文档。"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AlertStatus,
    CourseType,
    EnrollmentStatus,
    EnrollType,
    RiskLevel,
    RiskType,
    SemesterStatus,
    StudentStatus,
    UserRole,
    UserStatus,
)
from app.schemas.common import PageData, Resp, ok

ORM = ConfigDict(from_attributes=True)


# ============================ 认证 ============================
class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, description="学号或工号")
    password: str = Field(min_length=6, max_length=64)


class UserOut(BaseModel):
    model_config = ORM
    id: int
    username: str
    real_name: str
    role: UserRole
    status: UserStatus
    last_login_at: datetime | None = None


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserOut
    profile: "StudentBrief | TeacherBrief | None" = None


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=6, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


# ============================ 组织 ============================
class MajorIn(BaseModel):
    code: str
    name: str
    college: str
    duration_years: int = 4
    total_credits: int = 160
    degree: str = "工学学士"


class MajorOut(BaseModel):
    model_config = ORM
    id: int
    code: str
    name: str
    college: str
    duration_years: int
    total_credits: int
    degree: str


class ClassIn(BaseModel):
    name: str
    major_id: int
    grade_year: int
    counselor: str | None = None
    remark: str | None = None


class ClassOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    major_id: int
    grade_year: int
    counselor: str | None = None
    remark: str | None = None
    major_name: str | None = None
    student_count: int = 0


# ============================ 用户/学生 ============================
class StudentBrief(BaseModel):
    model_config = ORM
    id: int
    student_no: str
    name: str
    major_id: int
    class_id: int | None = None
    enrollment_year: int
    status: StudentStatus


class TeacherBrief(BaseModel):
    model_config = ORM
    id: int
    teacher_no: str
    name: str
    title: str
    college: str


class StudentCreateIn(BaseModel):
    username: str = Field(description="登录账号，一般与学号一致")
    password: str = Field(default="123456", min_length=6)
    student_no: str
    name: str
    gender: str = "M"
    major_id: int
    class_id: int | None = None
    enrollment_year: int
    phone: str | None = None
    email: str | None = None


class StudentUpdateIn(BaseModel):
    name: str | None = None
    gender: str | None = None
    major_id: int | None = None
    class_id: int | None = None
    status: StudentStatus | None = None
    phone: str | None = None
    email: str | None = None


class StudentOut(BaseModel):
    model_config = ORM
    id: int
    student_no: str
    name: str
    gender: str
    major_id: int
    class_id: int | None = None
    enrollment_year: int
    status: StudentStatus
    phone: str | None = None
    email: str | None = None
    major_name: str | None = None
    class_name: str | None = None


# ============================ 课程 ============================
class CourseIn(BaseModel):
    code: str
    name: str
    credits: float = Field(gt=0, le=20)
    hours: int = 48
    course_type: CourseType
    college: str = ""
    major_scope: str | None = None
    description: str | None = None
    is_active: bool = True


class PrereqOut(BaseModel):
    prerequisite_course_id: int
    prerequisite_course_name: str | None = None
    prerequisite_course_code: str | None = None
    min_score: int = 60
    allow_concurrent: bool = False


class CourseOut(BaseModel):
    model_config = ORM
    id: int
    code: str
    name: str
    credits: float
    hours: int
    course_type: CourseType
    college: str
    major_scope: str | None = None
    description: str | None = None
    is_active: bool
    prerequisite_names: list[str] = []
    prerequisites: list[PrereqOut] = []


class PrerequisiteIn(BaseModel):
    prerequisite_course_id: int
    min_score: int = 60
    allow_concurrent: bool = False


# ============================ 学期 ============================
class SemesterIn(BaseModel):
    code: str
    name: str
    academic_year: str
    term: int = Field(ge=1, le=2)
    start_date: date
    end_date: date
    select_start_at: datetime | None = None
    select_end_at: datetime | None = None
    status: SemesterStatus = SemesterStatus.PLANNING
    is_current: bool = False


class SemesterOut(BaseModel):
    model_config = ORM
    id: int
    code: str
    name: str
    academic_year: str
    term: int
    start_date: date
    end_date: date
    select_start_at: datetime | None = None
    select_end_at: datetime | None = None
    status: SemesterStatus
    is_current: bool
    offering_count: int = 0


# ============================ 开课计划 ============================
class TimeSlotIn(BaseModel):
    weekday: int = Field(ge=1, le=7)
    start_section: int = Field(ge=1, le=12)
    end_section: int = Field(ge=1, le=12)
    start_week: int = Field(default=1, ge=1, le=30)
    end_week: int = Field(default=16, ge=1, le=30)

    def validate_range(self) -> "TimeSlotIn":
        if self.end_section < self.start_section:
            raise ValueError("结束节次不能小于起始节次")
        if self.end_week < self.start_week:
            raise ValueError("结束周次不能小于起始周次")
        return self


class TimeSlotOut(BaseModel):
    model_config = ORM
    id: int
    weekday: int
    start_section: int
    end_section: int
    start_week: int
    end_week: int
    weeks_desc: str | None = None


class OfferingIn(BaseModel):
    course_id: int
    semester_id: int
    teacher_id: int | None = None
    class_name: str = "01班"
    capacity: int = Field(default=60, ge=1, le=1000)
    campus: str = "主校区"
    classroom: str = "待定"
    major_scope: str | None = None
    grade_scope: str | None = None
    is_open: bool = True
    remark: str | None = None
    time_slots: list[TimeSlotIn] = []


class OfferingUpdateIn(BaseModel):
    teacher_id: int | None = None
    class_name: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=1000)
    campus: str | None = None
    classroom: str | None = None
    major_scope: str | None = None
    grade_scope: str | None = None
    is_open: bool | None = None
    remark: str | None = None
    time_slots: list[TimeSlotIn] | None = None


class OfferingOut(BaseModel):
    model_config = ORM
    id: int
    course_id: int
    course_code: str | None = None
    course_name: str | None = None
    credits: float | None = None
    course_type: CourseType | None = None
    semester_id: int
    semester_code: str | None = None
    teacher_id: int | None = None
    teacher_name: str | None = None
    class_name: str
    capacity: int
    selected_count: int
    remaining: int = 0
    campus: str
    classroom: str
    major_scope: str | None = None
    grade_scope: str | None = None
    is_open: bool
    remark: str | None = None
    time_slots: list[TimeSlotOut] = []
    # 面向学生的附加信息
    selected: bool = False
    selectable: bool = True
    block_reason: str | None = None
    warnings: list[str] = []


# ============================ 选课 ============================
class SelectCourseIn(BaseModel):
    offering_id: int
    idempotent_key: str | None = Field(default=None, description="前端生成的幂等键，防重复提交")


class DropCourseIn(BaseModel):
    offering_id: int
    reason: str | None = None


class EnrollmentOut(BaseModel):
    model_config = ORM
    id: int
    student_id: int
    offering_id: int
    course_id: int
    semester_id: int
    status: EnrollmentStatus
    enroll_type: EnrollType
    credits: float
    select_at: datetime
    drop_at: datetime | None = None
    course_code: str | None = None
    course_name: str | None = None
    course_type: CourseType | None = None
    teacher_name: str | None = None
    class_name: str | None = None
    final_score: float | None = None
    grade_point: float | None = None
    time_slots: list[TimeSlotOut] = []


class RuleCheckItem(BaseModel):
    rule_key: str
    rule_name: str
    passed: bool
    level: str = "BLOCK"  # BLOCK=硬性拦截 WARN=提示
    message: str = ""


class PrecheckOut(BaseModel):
    offering_id: int
    selectable: bool
    checks: list[RuleCheckItem]
    current_credits: float = 0
    max_credits: float = 0


class BatchPrecheckIn(BaseModel):
    """一键预检：把当前学期所有可选教学班跑一遍规则，返回"能选的课"，用于推荐与体检报告。"""

    semester_id: int | None = None
    limit: int = 50


# ============================ 成绩 ============================
class GradeIn(BaseModel):
    enrollment_id: int
    usual_score: float | None = Field(default=None, ge=0, le=100)
    exam_score: float | None = Field(default=None, ge=0, le=100)
    final_score: float | None = Field(default=None, ge=0, le=100, description="不传则按 平时40%+期末60% 计算")
    usual_weight: float = Field(default=0.4, ge=0, le=1)
    remark: str | None = None


class BatchGradeIn(BaseModel):
    items: list[GradeIn]


class GradeOut(BaseModel):
    model_config = ORM
    id: int
    enrollment_id: int
    student_id: int
    course_id: int
    course_code: str | None = None
    course_name: str | None = None
    course_type: CourseType | None = None
    credits: float
    semester_id: int
    semester_name: str | None = None
    attempt_no: int
    usual_score: float | None = None
    exam_score: float | None = None
    final_score: float
    grade_point: float
    is_pass: bool
    is_retake: bool
    recorded_at: datetime
    remark: str | None = None


class GpaStatOut(BaseModel):
    overall_gpa: float
    total_credits_earned: float
    total_credits_attempted: float
    passed_course_count: int
    failed_course_count: int
    rank_in_class: int | None = None
    class_size: int | None = None
    by_semester: list[dict] = []


# ============================ 推荐 ============================
class RecommendOut(BaseModel):
    offering_id: int
    course_id: int
    course_code: str
    course_name: str
    credits: float
    course_type: CourseType
    teacher_name: str | None = None
    score: float = Field(description="综合推荐分 0-100")
    reason: list[str] = []
    cf_score: float = 0
    rule_score: float = 0
    remaining: int = 0
    time_slots: list[TimeSlotOut] = []


# ============================ 学业分析 ============================
class GraduationProgressOut(BaseModel):
    major_name: str
    required_total: float
    earned_total: float
    progress_percent: float
    by_type: list[dict] = []
    missing_required_courses: list[dict] = []
    estimated_status: str = ""
    suggestion: str = ""


class RiskAlertOut(BaseModel):
    model_config = ORM
    id: int
    student_id: int
    student_no: str | None = None
    student_name: str | None = None
    class_name: str | None = None
    semester_id: int | None = None
    risk_type: RiskType
    risk_level: RiskLevel
    risk_score: float
    title: str
    reason: str | None = None
    suggestion: str | None = None
    status: AlertStatus
    created_at: datetime


class RuleToggleIn(BaseModel):
    enabled: bool
    params: dict | None = None


class RuleOut(BaseModel):
    model_config = ORM
    id: int
    rule_key: str
    name: str
    description: str | None = None
    params: str | None = None
    priority: int
    enabled: bool


LoginOut.model_rebuild()
