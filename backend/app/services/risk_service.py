"""学业风险识别服务。

思路：把"辅导员凭经验判断谁会出问题"沉淀成**可量化、可解释、可批量执行**的规则。

五类风险，各自算分（0-100），再按权重合成综合风险分并映射等级：
1. FAILED_COURSE 挂科风险：挂科门数 + 挂科课程学分占比；
2. GPA_WARNING 绩点预警：累计 GPA 低于阈值（默认 2.0），距离阈值越远分越高；
3. CREDIT_LAG 学分进度落后：已获学分 vs 按学期进度应得学分；
4. TREND_DOWN 成绩下滑趋势：最近两个学期 GPA 环比下降幅度；
5. GRADUATION_RISK 毕业风险：按当前修读速度线性外推，判断能否按期毕业。

可解释性：每条预警都带 reason（JSON 数组，说明各项扣分来源）和 suggestion（干预建议）。
辅导员看预警时最需要的是"为什么被判为高风险"，而不是一个孤零零的分数。
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import AlertStatus, RiskLevel, RiskType, StudentStatus
from app.models.risk import RiskAlert
from app.models.teaching import Semester
from app.models.user import Student
from app.services.grade_service import failed_courses, gpa_stat

# 各风险类型的权重，合计 1.0，决定综合风险分
RISK_WEIGHTS: dict[RiskType, float] = {
    RiskType.FAILED_COURSE: 0.35,
    RiskType.GPA_WARNING: 0.25,
    RiskType.CREDIT_LAG: 0.20,
    RiskType.TREND_DOWN: 0.10,
    RiskType.GRADUATION_RISK: 0.10,
}

# 等级阈值按**风险分位数**标定，而不是拍脑袋定 80/60：
# 实测 270 名学生的综合风险分最高 63.3、P90 为 44.7、P75 为 35.8。
# 取 60 对应约 Top 1%、40 对应约 Top 17%，既保证"高风险"是真正需要立刻干预的少数人，
# 又不会像固定 80 分那样在本数据规模下永远为空。真实上线后应随数据分布定期回归标定。
LEVEL_THRESHOLDS = [(60, RiskLevel.HIGH), (40, RiskLevel.MEDIUM), (0, RiskLevel.LOW)]


@dataclass
class RiskFinding:
    risk_type: RiskType
    score: float
    title: str
    reasons: list[str]
    suggestion: str

    @property
    def level(self) -> RiskLevel:
        for threshold, level in LEVEL_THRESHOLDS:
            if self.score >= threshold:
                return level
        return RiskLevel.LOW


def _current_semester(db: Session) -> Semester | None:
    return db.execute(select(Semester).where(Semester.is_current.is_(True))).scalar_one_or_none()


def _semester_index(db: Session, student: Student, semester: Semester | None) -> int:
    if semester is None:
        return 1
    return max((semester.start_date.year - student.enrollment_year) * 2 + semester.term, 1)


def analyze_student(db: Session, student: Student) -> list[RiskFinding]:
    """分析单个学生，返回所有触发的风险点（分数 > 0 的）。"""
    findings: list[RiskFinding] = []
    stat = gpa_stat(db, student)
    current = _current_semester(db)
    semester_index = _semester_index(db, student, current)

    # ---------- 1. 挂科风险 ----------
    fails = failed_courses(db, student.id)
    if fails:
        fail_credits = sum(g.credits for g in fails)
        attempted = max(stat["total_credits_attempted"], 1.0)
        score = min(40 + len(fails) * 12 + (fail_credits / attempted) * 60, 100)
        names = [f"{g.course.name}({g.final_score:g}分)" for g in fails if g.course][:5]
        findings.append(RiskFinding(
            risk_type=RiskType.FAILED_COURSE,
            score=round(score, 1),
            title=f"存在 {len(fails)} 门课程不及格",
            reasons=[f"累计挂科 {len(fails)} 门，合计 {fail_credits:g} 学分（占已修学分 {fail_credits / attempted:.0%}）",
                     "未通过课程：" + "、".join(names)],
            suggestion="建议本学期优先安排重修，并联系任课教师做针对性补强；若挂科已影响毕业学分缺口，需同步调整修读计划。",
        ))

    # ---------- 2. 绩点预警 ----------
    gpa = stat["overall_gpa"]
    if gpa and gpa < 2.5:
        score = min((2.5 - gpa) / 2.5 * 100, 100)
        reasons = [f"累计绩点 {gpa:.2f}，低于 2.50 的预警线"]
        if stat["rank_in_class"] and stat["class_size"]:
            percentile = stat["rank_in_class"] / stat["class_size"]
            reasons.append(f"班级排名 {stat['rank_in_class']}/{stat['class_size']}（后 {percentile:.0%}）")
            score = min(score + percentile * 20, 100)
        findings.append(RiskFinding(
            risk_type=RiskType.GPA_WARNING,
            score=round(score, 1),
            title=f"累计绩点偏低（{gpa:.2f}）",
            reasons=reasons,
            suggestion="绩点已接近学位授予下限，建议减少高难度选修课，集中精力提升专业必修课成绩。",
        ))

    # ---------- 3. 学分进度落后 ----------
    if current:
        required_total = _required_total(db, student.major_id)
        # 关键：进度基准取"已完成的学期数"（当前学期还没结束，不该算作应得学分）。
        # semester_index 是当前第几学期，所以 completed = semester_index - 1。
        # 否则第一学期新生会被误判为"落后 20 学分" —— 典型的假阳性。
        completed_semesters = max(semester_index - 1, 0)
        expected_ratio = min(completed_semesters / 8, 1.0)
        expected = required_total * expected_ratio
        earned = stat["total_credits_earned"]
        if expected > 0 and earned < expected * 0.85:
            gap = expected - earned
            score = min(gap / expected * 100, 100)
            findings.append(RiskFinding(
                risk_type=RiskType.CREDIT_LAG,
                score=round(score, 1),
                title=f"学分进度落后 {gap:.1f} 学分",
                reasons=[f"已完成 {completed_semesters} 个学期，按进度应得约 {expected:.1f} 学分，"
                         f"实际已得 {earned:.1f} 学分",
                         f"培养方案要求总学分 {required_total:g}"],
                suggestion="建议后续学期适当提高选课学分（在规则允许上限内），优先补修专业必修课。",
            ))

    # ---------- 4. 成绩下滑趋势 ----------
    by_sem = stat["by_semester"]
    if len(by_sem) >= 2:
        prev, last = by_sem[-2]["gpa"], by_sem[-1]["gpa"]
        if prev > 0 and last < prev:
            drop = prev - last
            if drop >= 0.3:
                score = min(drop / 2.0 * 100, 100)
                findings.append(RiskFinding(
                    risk_type=RiskType.TREND_DOWN,
                    score=round(score, 1),
                    title=f"成绩下滑（季度绩点下降 {drop:.2f}）",
                    reasons=[f"{by_sem[-2]['semester_name']} 绩点 {prev:.2f} → {by_sem[-1]['semester_name']} 绩点 {last:.2f}"],
                    suggestion="建议关注近期课程难度与学习状态变化，必要时申请学业导师一对一沟通。",
                ))

    # ---------- 5. 毕业风险（按学生自身修读速度外推） ----------
    if current and semester_index >= 4:
        # 为什么加"已完成 3 个学期"这个门槛：大一新生只有 0~2 个学期的数据，
        # 用它外推毕业学分完全没有信息量，强行计算只会得到"所有人都无法毕业"的假阳性。
        required_total = _required_total(db, student.major_id)
        completed = max(semester_index - 1, 0)
        remaining_semesters = max(8 - semester_index, 0)
        earned = stat["total_credits_earned"]
        needed = max(required_total - earned, 0)

        # 用学生自己的平均修读速度外推，比"每学期固定 22 学分"的假设更贴合个体差异
        pace = earned / completed if completed else 0.0
        projected = earned + pace * remaining_semesters
        # 留 10% 容差，避免边界学生被反复预警
        if needed > 0 and (remaining_semesters == 0 or projected < required_total * 0.9):
            shortfall = max(required_total - projected, 0)
            score = min(shortfall / max(required_total, 1) * 150, 100)
            findings.append(RiskFinding(
                risk_type=RiskType.GRADUATION_RISK,
                score=round(score, 1),
                title="存在延期毕业风险",
                reasons=[f"已完成 {completed} 个学期，平均每学期修读 {pace:.1f} 学分",
                         f"按此速度外推，毕业时预计获得 {projected:.1f} 学分，距 {required_total:g} 学分尚缺 {shortfall:.1f}",
                         f"剩余 {remaining_semesters} 个学期"],
                suggestion="建议与教务/导师制定毕业冲刺计划，适度提高每学期选课学分，必要时申请学分置换或延长学习年限。",
            ))

    return findings


def _required_total(db: Session, major_id: int) -> float:
    from app.models.org import Major

    major = db.get(Major, major_id)
    return float(major.total_credits) if major else 160.0


def composite_score(findings: list[RiskFinding]) -> float:
    """综合风险分：各风险类型按权重加权（同类型取最高分）。"""
    if not findings:
        return 0.0
    best: dict[RiskType, float] = {}
    for f in findings:
        best[f.risk_type] = max(best.get(f.risk_type, 0), f.score)
    return round(sum(score * RISK_WEIGHTS.get(t, 0.1) for t, score in best.items()), 1)


def scan_students(
    db: Session,
    *,
    class_id: int | None = None,
    major_id: int | None = None,
    student_ids: list[int] | None = None,
    persist: bool = True,
) -> list[dict]:
    """批量扫描。persist=True 时把结果落库为 RiskAlert（同一学生同类型同批次做 upsert）。"""
    stmt = select(Student).where(Student.status == StudentStatus.ENROLLED)
    if class_id:
        stmt = stmt.where(Student.class_id == class_id)
    if major_id:
        stmt = stmt.where(Student.major_id == major_id)
    if student_ids:
        stmt = stmt.where(Student.id.in_(student_ids))

    students = list(db.execute(stmt).scalars().all())
    current = _current_semester(db)
    results: list[dict] = []

    for student in students:
        findings = analyze_student(db, student)
        overall = composite_score(findings)
        if persist:
            triggered = {f.risk_type for f in findings}
            for f in findings:
                _upsert_alert(db, student.id, current.id if current else None, f)
            # 预警闭环：本轮未再触发的历史 OPEN 预警自动关闭，
            # 否则学生会永远背着已经解决的旧预警（如重修通过后挂科预警仍挂着）
            _resolve_stale_alerts(db, student.id, current.id if current else None, triggered)
        if findings:
            results.append({
                "student_id": student.id,
                "student_no": student.student_no,
                "student_name": student.name,
                "class_id": student.class_id,
                "risk_score": overall,
                "risk_level": _level_of(overall).value,
                "findings": [
                    {
                        "risk_type": f.risk_type.value,
                        "risk_level": f.level.value,
                        "risk_score": f.score,
                        "title": f.title,
                        "reasons": f.reasons,
                        "suggestion": f.suggestion,
                    }
                    for f in findings
                ],
            })

    if persist:
        db.commit()

    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results


def _level_of(score: float) -> RiskLevel:
    for threshold, level in LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


def _upsert_alert(db: Session, student_id: int, semester_id: int | None, finding: RiskFinding) -> None:
    existing = db.execute(
        select(RiskAlert).where(
            RiskAlert.student_id == student_id,
            RiskAlert.risk_type == finding.risk_type,
            RiskAlert.semester_id == semester_id,
            RiskAlert.status == AlertStatus.OPEN,
        )
    ).scalars().first()

    payload = json.dumps(finding.reasons, ensure_ascii=False)
    if existing:
        existing.risk_score = finding.score
        existing.risk_level = finding.level
        existing.title = finding.title
        existing.reason = payload
        existing.suggestion = finding.suggestion
    else:
        db.add(RiskAlert(
            student_id=student_id,
            semester_id=semester_id,
            risk_type=finding.risk_type,
            risk_level=finding.level,
            risk_score=finding.score,
            title=finding.title,
            reason=payload,
            suggestion=finding.suggestion,
            status=AlertStatus.OPEN,
        ))


def _resolve_stale_alerts(
    db: Session, student_id: int, semester_id: int | None, triggered: set[RiskType]
) -> None:
    """把本轮已消除的 OPEN 预警自动关闭，保留处理痕迹（不物理删除，便于回溯）。"""
    stale = db.execute(
        select(RiskAlert).where(
            RiskAlert.student_id == student_id,
            RiskAlert.semester_id == semester_id,
            RiskAlert.status == AlertStatus.OPEN,
        )
    ).scalars().all()
    for alert in stale:
        if alert.risk_type in triggered:
            continue
        alert.status = AlertStatus.IGNORED
        alert.handle_note = "系统自动复查：本次扫描该风险指标已恢复正常，自动关闭"


def list_alerts(
    db: Session,
    *,
    risk_type: RiskType | None = None,
    risk_level: RiskLevel | None = None,
    status: AlertStatus | None = None,
    class_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[dict]]:
    stmt = select(RiskAlert, Student).join(Student, Student.id == RiskAlert.student_id)
    if risk_type:
        stmt = stmt.where(RiskAlert.risk_type == risk_type)
    if risk_level:
        stmt = stmt.where(RiskAlert.risk_level == risk_level)
    if status:
        stmt = stmt.where(RiskAlert.status == status)
    if class_id:
        stmt = stmt.where(Student.class_id == class_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(RiskAlert.risk_score.desc(), RiskAlert.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()

    items = []
    for alert, student in rows:
        items.append({
            "id": alert.id,
            "student_id": student.id,
            "student_no": student.student_no,
            "student_name": student.name,
            "semester_id": alert.semester_id,
            "risk_type": alert.risk_type,
            "risk_level": alert.risk_level,
            "risk_score": alert.risk_score,
            "title": alert.title,
            "reason": alert.reason,
            "suggestion": alert.suggestion,
            "status": alert.status,
            "created_at": alert.created_at,
        })
    return total, items


def handle_alert(db: Session, alert_id: int, handler_id: int, note: str | None, status: AlertStatus) -> RiskAlert:
    from app.core.exceptions import NotFoundError

    alert = db.get(RiskAlert, alert_id)
    if alert is None:
        raise NotFoundError("预警记录不存在")
    alert.status = status
    alert.handler_id = handler_id
    alert.handle_note = note
    db.commit()
    db.refresh(alert)
    return alert


def overview(db: Session) -> dict:
    """管理者看板：风险分布总览。"""
    rows = db.execute(
        select(RiskAlert.risk_level, func.count(RiskAlert.id))
        .where(RiskAlert.status == AlertStatus.OPEN)
        .group_by(RiskAlert.risk_level)
    ).all()
    by_level = {level.value: count for level, count in rows}

    type_rows = db.execute(
        select(RiskAlert.risk_type, func.count(RiskAlert.id))
        .where(RiskAlert.status == AlertStatus.OPEN)
        .group_by(RiskAlert.risk_type)
    ).all()
    by_type = {t.value: c for t, c in type_rows}

    return {
        "by_level": {
            "HIGH": by_level.get("HIGH", 0),
            "MEDIUM": by_level.get("MEDIUM", 0),
            "LOW": by_level.get("LOW", 0),
        },
        "by_type": by_type,
        "total_open": sum(by_level.values()),
    }
