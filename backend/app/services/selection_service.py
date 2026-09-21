"""选课服务：并发安全是这里的核心命题。

一次"选课"要同时保证三件事：
1. 不超卖：教学班容量 60，绝不能选进第 61 个人；
2. 不重复：同一学生同一门课本学期只有一条有效记录；
3. 不冲突：时间不打架、先修课满足、学分不超上限。

对应三道防线：
- 第一道 Redis 幂等键：挡住用户狂点"选课"按钮产生的重复请求（网络重试/双击）；
- 第二道 Redis 分布式锁：多实例部署时同一教学班的请求先在入口排队，降低 DB 争用；
- 第三道 MySQL 行锁（SELECT ... FOR UPDATE）：最终一致性保障，真正的"扣库存"。

为什么锁顺序必须是「学生 → 教学班」且全局统一：两条事务如果以相反顺序加锁就会互相等待，
形成死锁（MySQL 报 1213）。统一加锁顺序是最省事也最有效的死锁预防手段。
即便如此，仍保留死锁重试兜底 —— 生产上"能自愈"比"永不出错"更现实。

关于隔离级别：默认 REPEATABLE READ 下，普通 SELECT 读的是快照，
`SELECT ... FOR UPDATE` 才会读最新已提交数据并加排他锁，
所以扣减前必须用它把 offering 重新读一遍，否则计数会基于脏快照算错。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.exceptions import BizError, ConflictError, NotFoundError
from app.core.redis_client import RedisLock, cache_delete_prefix, get_redis
from app.models.course import CoursePrerequisite
from app.models.enrollment import Enrollment
from app.models.enums import EnrollmentStatus, EnrollType
from app.models.teaching import CourseOffering, Semester
from app.models.user import Student
from app.services.academic import AcademicState, build_academic_state, load_offering
from app.services.rule_engine import BLOCK, RuleContext, RuleEngine

logger = logging.getLogger(__name__)

MAX_RETRY = 3


# ---------------------------------------------------------------------------
# 幂等
# ---------------------------------------------------------------------------
def _idempotent_key(student_id: int, offering_id: int, key: str) -> str:
    return f"select:idem:{student_id}:{offering_id}:{key}"


def _check_idempotent(student_id: int, offering_id: int, key: str | None) -> None:
    """命中幂等键说明是重复提交，直接拒绝，避免产生第二条选课流水。"""
    if not key:
        return
    try:
        client = get_redis()
        full = _idempotent_key(student_id, offering_id, key)
        if not client.set(full, "1", nx=True, ex=60):
            raise ConflictError("请求正在处理或已提交，请勿重复点击", code="DUPLICATE_SUBMIT")
    except ConflictError:
        raise
    except Exception:  # Redis 不可用时幂等降级，靠 DB 唯一约束兜底
        pass


def _release_idempotent(student_id: int, offering_id: int, key: str | None) -> None:
    if not key:
        return
    try:
        get_redis().delete(_idempotent_key(student_id, offering_id, key))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 规则校验
# ---------------------------------------------------------------------------
def evaluate_offering(
    db: Session,
    student: Student,
    offering: CourseOffering,
    state: AcademicState | None = None,
) -> tuple[bool, list, AcademicState]:
    """对学生 + 教学班跑一遍规则引擎，返回 (是否可提交, 结果列表, 学业快照)。"""
    semester = offering.semester or db.get(Semester, offering.semester_id)
    if state is None:
        state = build_academic_state(db, student, semester)

    course = offering.course
    prerequisites = db.execute(
        select(CoursePrerequisite)
        .options(selectinload(CoursePrerequisite.prerequisite))
        .where(CoursePrerequisite.course_id == offering.course_id)
    ).scalars().all()

    extra_params = {
        "max_credits": offering.credit_limit or settings.DEFAULT_MAX_CREDITS_PER_SEMESTER,
        "pass_score": settings.PASS_SCORE,
        "semester_count": _semester_count(db, student, semester),
    }
    engine = RuleEngine.from_db(db, extra_params)
    ctx = RuleContext(state=state, offering=offering, course=course, prerequisites=list(prerequisites))
    return (*engine.evaluate(ctx), state)


def _semester_count(db: Session, student: Student, semester: Semester | None) -> int:
    """当前是入学后第几个学期，用于毕业缺口类规则。"""
    if semester is None:
        return 1
    return max((semester.start_date.year - student.enrollment_year) * 2 + semester.term, 1)


# ---------------------------------------------------------------------------
# 选课
# ---------------------------------------------------------------------------
def select_course(
    db: Session,
    student: Student,
    offering_id: int,
    idempotent_key: str | None = None,
) -> Enrollment:
    _check_idempotent(student.id, offering_id, idempotent_key)

    try:
        with RedisLock(f"offering:{offering_id}", timeout=settings.SELECT_LOCK_TIMEOUT, wait=2.0):
            for attempt in range(1, MAX_RETRY + 1):
                try:
                    enrollment = _select_in_transaction(db, student, offering_id)
                    cache_delete_prefix("cache:offering")
                    cache_delete_prefix(f"cache:recommend:{student.id}")
                    return enrollment
                except OperationalError as exc:
                    db.rollback()
                    # 1213 = Deadlock found，1205 = Lock wait timeout，两者都可重试
                    if attempt < MAX_RETRY and _is_retryable(exc):
                        logger.warning("选课遇到锁冲突，第 %s 次重试: %s", attempt, exc)
                        continue
                    raise ConflictError("选课请求过于集中，请稍后重试", code="LOCK_CONTENTION") from exc
                except Exception:
                    db.rollback()
                    raise
    finally:
        _release_idempotent(student.id, offering_id, idempotent_key)

    raise ConflictError("选课失败，请重试")


def _is_retryable(exc: OperationalError) -> bool:
    text = str(exc.orig) if exc.orig else str(exc)
    return "1213" in text or "1205" in text or "Deadlock" in text


def _select_in_transaction(db: Session, student: Student, offering_id: int) -> Enrollment:
    # ① 锁学生行：把同一学生的并发选课串行化，防止"同时选两门冲突课程"都通过
    locked_student = db.execute(
        select(Student).where(Student.id == student.id).with_for_update()
    ).scalar_one_or_none()
    if locked_student is None:
        raise NotFoundError("学生档案不存在")

    # ② 锁教学班行：拿到最新 selected_count，这是防超卖的关键一步
    offering = db.execute(
        select(CourseOffering).where(CourseOffering.id == offering_id).with_for_update()
    ).scalar_one_or_none()
    if offering is None:
        raise NotFoundError("教学班不存在")

    offering = load_offering(db, offering.id) or offering  # 补上 time_slots 等关联
    course = offering.course

    # ③ 查已有选课记录：退课后再选要复用同一行（唯一约束限制）
    existing = db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.course_id == offering.course_id,
            Enrollment.semester_id == offering.semester_id,
        )
    ).scalar_one_or_none()

    # 已选未退直接判定为冲突（409），不必再跑一遍规则引擎：
    # 语义上这是"资源已存在"，与"不满足条件"是两类错误，前端要能区分处理
    if existing is not None and existing.status != EnrollmentStatus.DROPPED:
        raise ConflictError("本学期已选该课程，请勿重复提交", code="ALREADY_SELECTED")

    # ④ 规则引擎全量校验
    passed, results, state = evaluate_offering(db, locked_student, offering)
    if not passed:
        failed = [r.message for r in results if not r.passed and r.level == BLOCK]
        raise BizError("；".join(failed[:3]) or "不满足选课条件", code="RULE_REJECTED")

    # ⑤ 容量再确认：行锁已拿到最新值，这里的判断是准确的
    if offering.selected_count >= offering.capacity:
        raise ConflictError(f"《{course.name}》选课人数已满（{offering.capacity} 人）", code="OFFERING_FULL")

    is_retake = offering.course_id in state.best_score

    if existing is not None:
        # 退课后重新选：复用原记录，保持唯一约束不冲突
        existing.status = EnrollmentStatus.SELECTED
        existing.offering_id = offering.id
        existing.enroll_type = EnrollType.RETAKE if is_retake else EnrollType.NORMAL
        existing.credits = course.credits
        existing.select_at = datetime.now()
        existing.drop_at = None
        enrollment = existing
    else:
        enrollment = Enrollment(
            student_id=student.id,
            offering_id=offering.id,
            course_id=offering.course_id,
            semester_id=offering.semester_id,
            status=EnrollmentStatus.SELECTED,
            enroll_type=EnrollType.RETAKE if is_retake else EnrollType.NORMAL,
            credits=course.credits,
        )
        db.add(enrollment)

    # ⑥ 扣减容量（在行锁保护下 read-modify-write）
    offering.selected_count += 1
    db.commit()
    db.refresh(enrollment)
    return enrollment


# ---------------------------------------------------------------------------
# 退课
# ---------------------------------------------------------------------------
def drop_course(db: Session, student: Student, offering_id: int, reason: str | None = None) -> None:
    offering = db.execute(
        select(CourseOffering).where(CourseOffering.id == offering_id).with_for_update()
    ).scalar_one_or_none()
    if offering is None:
        raise NotFoundError("教学班不存在")

    enrollment = db.execute(
        select(Enrollment)
        .where(
            Enrollment.student_id == student.id,
            Enrollment.offering_id == offering_id,
            Enrollment.status != EnrollmentStatus.DROPPED,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("未找到该选课记录")

    enrollment.status = EnrollmentStatus.DROPPED
    enrollment.drop_at = datetime.now()
    enrollment.drop_reason = reason
    # 容量回滚，同样在行锁下做，避免"退了但名额没还回去"
    offering.selected_count = max(offering.selected_count - 1, 0)
    db.commit()
    cache_delete_prefix("cache:offering")
    cache_delete_prefix(f"cache:recommend:{student.id}")


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def list_my_enrollments(
    db: Session,
    student: Student,
    semester_id: int | None = None,
    *,
    all_semesters: bool = False,
) -> list[Enrollment]:
    """默认只查当前学期 —— 学生打开"我的选课/课表"时想看的是本学期，
    历史记录需要显式传 semester_id 或 all_semesters=True。"""
    if semester_id is None and not all_semesters:
        current = db.execute(
            select(Semester).where(Semester.is_current.is_(True))
        ).scalar_one_or_none()
        if current is not None:
            semester_id = current.id

    stmt = (
        select(Enrollment)
        .options(
            selectinload(Enrollment.course),
            selectinload(Enrollment.offering).selectinload(CourseOffering.time_slots),
            selectinload(Enrollment.offering).selectinload(CourseOffering.teacher),
            selectinload(Enrollment.grade),
        )
        .where(Enrollment.student_id == student.id, Enrollment.status != EnrollmentStatus.DROPPED)
        .order_by(Enrollment.id.desc())
    )
    if semester_id:
        stmt = stmt.where(Enrollment.semester_id == semester_id)
    return list(db.execute(stmt).scalars().all())


def build_timetable(db: Session, student: Student, semester_id: int | None = None) -> dict:
    """生成课表：按 周一~周日 × 节次 的网格返回，前端直接渲染表格。"""
    enrollments = list_my_enrollments(db, student, semester_id)
    grid: dict[str, list[dict]] = {f"{d}-{s}": [] for d in range(1, 8) for s in range(1, 13)}
    courses: list[dict] = []

    for en in enrollments:
        course = en.course
        teacher_name = en.offering.teacher.name if en.offering and en.offering.teacher else "待定"
        slots = []
        for slot in (en.offering.time_slots if en.offering else []):
            cell = {
                "course_name": course.name,
                "course_code": course.code,
                "teacher_name": teacher_name,
                "classroom": en.offering.classroom,
                "color_key": course.id % 8,
                "enrollment_id": en.id,
            }
            for section in range(slot.start_section, slot.end_section + 1):
                grid[f"{slot.weekday}-{section}"].append(cell)
            slots.append(
                {
                    "weekday": slot.weekday,
                    "start_section": slot.start_section,
                    "end_section": slot.end_section,
                    "start_week": slot.start_week,
                    "end_week": slot.end_week,
                    "weeks_desc": slot.weeks_desc,
                }
            )
        courses.append(
            {
                "enrollment_id": en.id,
                "course_id": course.id,
                "course_name": course.name,
                "course_code": course.code,
                "credits": en.credits,
                "course_type": course.course_type,
                "teacher_name": teacher_name,
                "classroom": en.offering.classroom if en.offering else "",
                "class_name": en.offering.class_name if en.offering else "",
                "time_slots": slots,
            }
        )

    return {
        "grid": grid,
        "courses": courses,
        "total_credits": round(sum(c["credits"] for c in courses), 1),
        "course_count": len(courses),
    }


def export_timetable_json(enrollments: list[Enrollment]) -> str:
    payload = [
        {
            "course": e.course.name,
            "teacher": e.offering.teacher.name if e.offering and e.offering.teacher else "",
            "classroom": e.offering.classroom if e.offering else "",
            "slots": [(s.weekday, s.start_section, s.end_section) for s in (e.offering.time_slots if e.offering else [])],
        }
        for e in enrollments
    ]
    return json.dumps(payload, ensure_ascii=False)
