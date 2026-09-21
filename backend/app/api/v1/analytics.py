"""学业分析接口：毕业进度、学业风险、规则配置、管理看板。

这个模块是整个系统里"决策"味最重的一层：
- 学生侧：毕业进度 + 个人风险体检 -> 知道自己该干什么；
- 管理侧：批量风险扫描 + 看板 -> 知道该介入谁。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.deps import AdminUser, CurrentStudent, DbSession, TeacherUser
from app.core.exceptions import NotFoundError
from app.core.redis_client import cache_delete_prefix
from app.models.enums import AlertStatus, RiskLevel, RiskType
from app.models.rule import SelectRule
from app.models.user import Student
from app.schemas import GraduationProgressOut, Resp, RiskAlertOut, RuleOut, RuleToggleIn
from app.services import graduation_service, risk_service
from app.services.rule_engine import RULE_REGISTRY

router = APIRouter(tags=["学业分析"])


# ============================== 学生侧 ==============================
@router.get("/analysis/graduation", response_model=Resp[GraduationProgressOut], summary="学生：毕业进度分析")
def graduation(db: DbSession, student: CurrentStudent):
    return {"code": "OK", "message": "success", "data": graduation_service.graduation_progress(db, student)}


@router.get("/analysis/my-risk", response_model=Resp[dict], summary="学生：个人学业风险体检")
def my_risk(db: DbSession, student: CurrentStudent):
    findings = risk_service.analyze_student(db, student)
    return {
        "code": "OK",
        "message": "success",
        "data": {
            "student_no": student.student_no,
            "student_name": student.name,
            "risk_score": risk_service.composite_score(findings),
            "risk_level": risk_service._level_of(risk_service.composite_score(findings)).value if findings else "LOW",
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
            "healthy": not findings,
        },
    }


# ============================== 管理侧 ==============================
@router.post("/analysis/risk-scan", response_model=Resp[dict], summary="管理员：批量学业风险扫描")
def risk_scan(
    db: DbSession,
    _: AdminUser,
    class_id: int | None = Query(default=None),
    major_id: int | None = Query(default=None),
    persist: bool = Query(default=True, description="是否把结果落库为预警记录"),
):
    """批量扫描并落库。生产环境应由定时任务（如每日凌晨）触发，避免人工点击。

    这里同步执行是为了演示与联调方便；数据量大时应改为异步任务 + 进度查询。
    """
    results = risk_service.scan_students(db, class_id=class_id, major_id=major_id, persist=persist)
    high = [r for r in results if r["risk_level"] == "HIGH"]
    return {
        "code": "OK",
        "message": f"扫描完成，共 {len(results)} 名学生存在风险，其中高风险 {len(high)} 人",
        "data": {"scanned": len(results), "high_risk": len(high), "items": results},
    }


@router.get("/analysis/alerts", response_model=Resp[dict], summary="管理员：学业预警列表")
def alerts(
    db: DbSession,
    _: TeacherUser,
    risk_type: RiskType | None = Query(default=None),
    risk_level: RiskLevel | None = Query(default=None),
    status: AlertStatus | None = Query(default=AlertStatus.OPEN),
    class_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    total, items = risk_service.list_alerts(
        db, risk_type=risk_type, risk_level=risk_level, status=status,
        class_id=class_id, page=page, page_size=page_size,
    )
    return {"code": "OK", "message": "success",
            "data": {"total": total, "page": page, "page_size": page_size, "items": items}}


@router.post("/analysis/alerts/{alert_id}/handle", response_model=Resp[dict], summary="管理员：处理预警")
def handle_alert(
    alert_id: int,
    db: DbSession,
    user: TeacherUser,
    status: AlertStatus = Query(default=AlertStatus.HANDLED),
    note: str | None = Query(default=None),
):
    risk_service.handle_alert(db, alert_id, user.id, note, status)
    return {"code": "OK", "message": "处理状态已更新", "data": None}


@router.get("/analysis/student/{student_id}/report", response_model=Resp[dict], summary="管理员：学生学业报告")
def student_report(student_id: int, db: DbSession, _: TeacherUser):
    """把毕业进度 + 风险体检 + 成绩统计合成一份"学生画像"，辅导员谈话前先看这个。"""
    from app.services.grade_service import gpa_stat

    student = db.get(Student, student_id)
    if student is None:
        raise NotFoundError("学生不存在")

    findings = risk_service.analyze_student(db, student)
    return {
        "code": "OK",
        "message": "success",
        "data": {
            "student": {
                "id": student.id,
                "student_no": student.student_no,
                "name": student.name,
                "class_id": student.class_id,
                "enrollment_year": student.enrollment_year,
                "status": student.status,
            },
            "gpa_stat": gpa_stat(db, student),
            "graduation": graduation_service.graduation_progress(db, student),
            "risk": {
                "risk_score": risk_service.composite_score(findings),
                "findings": [
                    {"risk_type": f.risk_type.value, "risk_level": f.level.value,
                     "title": f.title, "reasons": f.reasons, "suggestion": f.suggestion}
                    for f in findings
                ],
            },
        },
    }


@router.get("/analysis/dashboard", response_model=Resp[dict], summary="管理员：教务数据看板")
def dashboard(db: DbSession, _: TeacherUser):
    return {
        "code": "OK",
        "message": "success",
        "data": {
            "counters": graduation_service.class_statistics(db),
            "risk_overview": risk_service.overview(db),
        },
    }


# ============================== 规则配置 ==============================
@router.get("/rules", response_model=Resp[list[RuleOut]], summary="管理员：选课规则列表")
def list_rules(db: DbSession, _: TeacherUser):
    rules = db.execute(select(SelectRule).order_by(SelectRule.priority)).scalars().all()
    if not rules:
        # 库中没有配置时，暴露代码内置规则，前端仍可展示
        return {
            "code": "OK",
            "message": "success",
            "data": [
                {
                    "id": -i - 1,
                    "rule_key": r.rule_key,
                    "name": r.name,
                    "description": "内置默认规则（未落库）",
                    "params": json.dumps(r.default_params, ensure_ascii=False),
                    "priority": r.default_priority,
                    "enabled": True,
                }
                for i, r in enumerate(sorted(RULE_REGISTRY.values(), key=lambda x: x.default_priority))
            ],
        }
    return {"code": "OK", "message": "success", "data": [RuleOut.model_validate(r).model_dump() for r in rules]}


@router.put("/rules/{rule_id}", response_model=Resp[RuleOut], summary="管理员：启停/调参选课规则")
def update_rule(rule_id: int, payload: RuleToggleIn, db: DbSession, _: AdminUser):
    """改规则不改代码：开关一条规则或调整参数，清缓存即刻生效。

    这是"可配置化"的落地形态——毕业选课高峰想临时放宽学分上限，
    管理员在后台把 credit_limit 的 max_credits 从 30 改成 32 即可，
    不需要研发发版，也不影响正在进行的事务。
    """
    rule = db.get(SelectRule, rule_id)
    if rule is None:
        raise NotFoundError("规则不存在")
    rule.enabled = payload.enabled
    if payload.params is not None:
        rule.params = json.dumps(payload.params, ensure_ascii=False)
    db.commit()
    db.refresh(rule)

    # 规则配置变了，缓存里的推荐结果与列表需要失效
    cache_delete_prefix("cache:recommend")
    cache_delete_prefix("cache:offering")
    return {"code": "OK", "message": "规则已更新", "data": RuleOut.model_validate(rule).model_dump()}
