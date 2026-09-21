"""选课规则引擎。

设计模式：**责任链 + 策略模式 + 注册表**
- 每个规则是一个独立的 Rule 子类，只关心"给定上下文，这门课能不能选"；
- RuleEngine 按 t_select_rule 配置的优先级依次执行；管理员可开关规则、改参数，
  不改一行代码就能调整选课策略（毕业旺季把学分上限从 30 调到 28，改数据即可）；
- 故意**不做短路**：即使第一条就拦住了，也把全部规则跑完，
  这样前端能一次给出完整"选课体检报告"，而不是让用户试错式地点十次——体验和排查效率都更好。

规则的两种级别：
- BLOCK：硬性拦截，选课失败；
- WARN：仅提示，仍可提交（例如"该课程为选修，与你的毕业缺口匹配度低"）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.course import Course, CoursePrerequisite
from app.models.enums import CourseType, SemesterStatus, StudentStatus
from app.models.rule import SelectRule
from app.models.teaching import CourseOffering
from app.services.academic import AcademicState, TimeBlock, offering_time_blocks, sections_to_text

BLOCK = "BLOCK"
WARN = "WARN"


@dataclass
class RuleContext:
    """规则执行上下文。规则只读它，不查库、不写库 —— 纯函数才好测。"""

    state: AcademicState
    offering: CourseOffering
    course: Course
    prerequisites: list[CoursePrerequisite]
    # course_id -> 已选同名课程的教学班（用于冲突提示）
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleResult:
    rule_key: str
    rule_name: str
    passed: bool
    level: str = BLOCK
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_key": self.rule_key,
            "rule_name": self.rule_name,
            "passed": self.passed,
            "level": self.level,
            "message": self.message,
        }


class BaseRule:
    """规则基类。子类实现 check()，只返回结果，不产生副作用。"""

    rule_key: str = "base"
    name: str = "基础规则"
    default_priority: int = 100
    default_params: dict[str, Any] = {}

    def check(self, ctx: RuleContext) -> RuleResult:
        raise NotImplementedError

    def result(self, passed: bool, message: str = "", level: str = BLOCK) -> RuleResult:
        return RuleResult(rule_key=self.rule_key, rule_name=self.name, passed=passed, level=level, message=message)


# ---------------------------------------------------------------------------
# 1. 选课时间窗口
# ---------------------------------------------------------------------------
class SemesterWindowRule(BaseRule):
    rule_key = "semester_window"
    name = "选课时间窗口"
    default_priority = 10

    def check(self, ctx: RuleContext) -> RuleResult:
        from datetime import datetime

        sem = ctx.state.semester
        if sem is None:
            return self.result(False, "未指定学期，无法选课")
        if sem.status == SemesterStatus.PLANNING:
            return self.result(False, "该学期尚未开放选课")
        if sem.status in (SemesterStatus.ONGOING, SemesterStatus.FINISHED):
            return self.result(False, f"选课已截止（学期状态：{sem.status}）")
        if ctx.offering.semester_id != sem.id:
            return self.result(False, "该教学班不属于当前学期")
        now = datetime.now()
        if sem.select_start_at and now < sem.select_start_at:
            return self.result(False, f"选课尚未开始，开放时间 {sem.select_start_at:%Y-%m-%d %H:%M}")
        if sem.select_end_at and now > sem.select_end_at:
            return self.result(False, f"选课已于 {sem.select_end_at:%Y-%m-%d %H:%M} 截止")
        return self.result(True, "在选课时间内")


# ---------------------------------------------------------------------------
# 2. 教学班开放状态
# ---------------------------------------------------------------------------
class OfferingOpenRule(BaseRule):
    rule_key = "offering_open"
    name = "教学班开放状态"
    default_priority = 20

    def check(self, ctx: RuleContext) -> RuleResult:
        if not ctx.offering.is_open:
            return self.result(False, "该教学班已停止选课")
        if ctx.state.student.status != StudentStatus.ENROLLED:
            return self.result(False, "学籍状态非在读，无法选课")
        return self.result(True, "教学班可选")


# ---------------------------------------------------------------------------
# 3. 面向范围（专业 / 年级）
# ---------------------------------------------------------------------------
class ScopeMatchRule(BaseRule):
    rule_key = "scope_match"
    name = "专业年级范围"
    default_priority = 30

    @staticmethod
    def _match(scope: str | None, value: str) -> bool:
        if not scope:
            return True  # 空 = 不限
        return value in {s.strip() for s in scope.split(",") if s.strip()}

    def check(self, ctx: RuleContext) -> RuleResult:
        stu = ctx.state.student
        if not self._match(ctx.offering.major_scope, str(stu.major_id)):
            return self.result(False, "该教学班不面向你所在专业开放")
        if not self._match(ctx.offering.grade_scope, str(stu.enrollment_year)):
            return self.result(False, "该教学班不面向你所在年级开放")
        return self.result(True, "符合面向范围")


# ---------------------------------------------------------------------------
# 4. 本学期重复选同一门课
# ---------------------------------------------------------------------------
class DuplicateCourseRule(BaseRule):
    rule_key = "duplicate_course"
    name = "同课重复选校验"
    default_priority = 40

    def check(self, ctx: RuleContext) -> RuleResult:
        if ctx.offering.course_id in ctx.state.selected_course_ids:
            return self.result(False, "本学期已选该课程，不能重复选择")
        return self.result(True, "未重复选课")


# ---------------------------------------------------------------------------
# 5. 已修读过且及格（默认只提示，重修需走重修流程）
# ---------------------------------------------------------------------------
class AlreadyPassedRule(BaseRule):
    rule_key = "already_passed"
    name = "已修读课程校验"
    default_priority = 50

    def check(self, ctx: RuleContext) -> RuleResult:
        score = ctx.state.best_score.get(ctx.offering.course_id)
        if score is None:
            return self.result(True, "首次修读")
        if score >= ctx.params.get("pass_score", 60):
            return self.result(
                False,
                f"该课程你已修读并及格（{score:g} 分），如需重修请在重修通道申请",
                level=WARN,
            )
        return self.result(
            True,
            f"该课程曾不及格（{score:g} 分），本次为重修，成绩单将保留两次记录",
            level=WARN,
        )


# ---------------------------------------------------------------------------
# 6. 先修课
# ---------------------------------------------------------------------------
class PrerequisiteRule(BaseRule):
    rule_key = "prerequisite"
    name = "先修课校验"
    default_priority = 60

    def check(self, ctx: RuleContext) -> RuleResult:
        if not ctx.prerequisites:
            return self.result(True, "无先修课要求")
        missing: list[str] = []
        for pre in ctx.prerequisites:
            score = ctx.state.best_score.get(pre.prerequisite_course_id)
            if score is None:
                name = pre.prerequisite.name if pre.prerequisite else str(pre.prerequisite_course_id)
                missing.append(f"{name}（未修读）")
            elif score < pre.min_score:
                name = pre.prerequisite.name if pre.prerequisite else str(pre.prerequisite_course_id)
                missing.append(f"{name}（{score:g} 分，要求 ≥{pre.min_score}）")
        if missing:
            return self.result(False, "先修课未满足：" + "、".join(missing))
        return self.result(True, f"已满足 {len(ctx.prerequisites)} 门先修课要求")


# ---------------------------------------------------------------------------
# 7. 时间冲突
# ---------------------------------------------------------------------------
class TimeConflictRule(BaseRule):
    rule_key = "time_conflict"
    name = "上课时间冲突检测"
    default_priority = 70

    def check(self, ctx: RuleContext) -> RuleResult:
        target = offering_time_blocks(ctx.offering, ctx.course.name)
        if not target:
            return self.result(True, "该教学班未排课（时间待定），请留意后续通知", level=WARN)

        conflicts: list[str] = []
        for block in target:
            for occupied in ctx.state.time_blocks:
                if block.conflicts_with(occupied):
                    desc = f"{sections_to_text_like(block)} 与《{occupied.source}》冲突"
                    if desc not in conflicts:
                        conflicts.append(desc)
        if conflicts:
            return self.result(False, "时间冲突：" + "；".join(conflicts[:3]))
        return self.result(True, "无时间冲突")


def sections_to_text_like(block: TimeBlock) -> str:
    return f"周{'一二三四五六日'[block.weekday - 1]}第{block.start_section}-{block.end_section}节({block.start_week}-{block.end_week}周)"


# ---------------------------------------------------------------------------
# 8. 学分上限（含挂科预警学生的动态收紧）
# ---------------------------------------------------------------------------
class CreditLimitRule(BaseRule):
    rule_key = "credit_limit"
    name = "学期学分上限"
    default_priority = 80

    def check(self, ctx: RuleContext) -> RuleResult:
        max_credits = float(ctx.params.get("max_credits") or ctx.state.max_credits)
        # 学业预警学生（GPA 过低）动态收紧学分上限，把"决策"落到规则里
        warn_gpa = float(ctx.params.get("warn_gpa", 1.5))
        tighten = float(ctx.params.get("tighten_credits", 6))
        if ctx.state.overall_gpa and ctx.state.overall_gpa < warn_gpa:
            max_credits = max(max_credits - tighten, 6)
            tip = f"（因累计绩点偏低，学分上限下调为 {max_credits:g}）"
        else:
            tip = ""

        projected = ctx.state.current_credits + ctx.course.credits
        if projected > max_credits:
            return self.result(
                False,
                f"超出本学期学分上限：已选 {ctx.state.current_credits:g} + 本课 {ctx.course.credits:g} "
                f"= {projected:g} > {max_credits:g}{tip}",
            )
        return self.result(True, f"学分校验通过：{projected:g}/{max_credits:g}{tip}")


# ---------------------------------------------------------------------------
# 9. 课程类别与毕业缺口匹配（只提示，帮助学生做学业决策）
# ---------------------------------------------------------------------------
class GraduationGapRule(BaseRule):
    rule_key = "graduation_gap"
    name = "毕业缺口匹配度"
    default_priority = 90

    def check(self, ctx: RuleContext) -> RuleResult:
        # 该规则只做提示，不拦截
        semester_count = ctx.params.get("semester_count")
        if semester_count and semester_count >= 7 and ctx.course.course_type == CourseType.GENERAL:
            return self.result(
                True,
                "临近毕业，通识选修对毕业进度帮助有限，建议优先补齐专业必修学分",
                level=WARN,
            )
        return self.result(True, "课程类别无异常")


# ---------------------------------------------------------------------------
# 引擎本体
# ---------------------------------------------------------------------------
RULE_REGISTRY: dict[str, BaseRule] = {
    r.rule_key: r
    for r in [
        SemesterWindowRule(),
        OfferingOpenRule(),
        ScopeMatchRule(),
        DuplicateCourseRule(),
        AlreadyPassedRule(),
        PrerequisiteRule(),
        TimeConflictRule(),
        CreditLimitRule(),
        GraduationGapRule(),
    ]
}


class RuleEngine:
    """按配置加载启用的规则，逐条执行并汇总结果。"""

    def __init__(self, rules: list[BaseRule], config: dict[str, dict[str, Any]] | None = None):
        self.rules = rules
        self.config = config or {}

    @classmethod
    def from_db(cls, db: Session, extra_params: dict[str, Any] | None = None) -> "RuleEngine":
        rows = db.execute(
            select(SelectRule).where(SelectRule.enabled.is_(True)).order_by(SelectRule.priority)
        ).scalars().all()

        rules: list[BaseRule] = []
        config: dict[str, dict[str, Any]] = {}
        for row in rows:
            impl = RULE_REGISTRY.get(row.rule_key)
            if impl is None:
                continue  # 配置里存在但代码未实现的规则，安全跳过
            rules.append(impl)
            merged = dict(impl.default_params)
            merged.update(row.params_dict)
            if extra_params:
                merged.update(extra_params)
            config[row.rule_key] = merged

        if not rules:
            # 数据库还没初始化规则时，用代码内置默认值兜底，保证系统可用
            rules = sorted(RULE_REGISTRY.values(), key=lambda r: r.default_priority)
            config = {r.rule_key: dict(r.default_params) for r in rules}
            if extra_params:
                for key in config:
                    config[key].update(extra_params)

        return cls(rules, config)

    def evaluate(self, ctx: RuleContext) -> tuple[bool, list[RuleResult]]:
        """返回 (是否可提交, 全部规则结果)。全部规则跑完，不短路。"""
        results: list[RuleResult] = []
        for rule in self.rules:
            ctx.params = self.config.get(rule.rule_key, {})
            try:
                results.append(rule.check(ctx))
            except Exception as exc:  # 单条规则异常不影响整体选课流程
                results.append(
                    RuleResult(rule.rule_key, rule.name, True, WARN, f"规则执行异常已跳过：{exc}")
                )
        blocking = [r for r in results if not r.passed and r.level == BLOCK]
        return len(blocking) == 0, results
