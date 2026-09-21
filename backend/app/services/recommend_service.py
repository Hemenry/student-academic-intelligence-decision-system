"""课程推荐服务：协同过滤召回 + 规则引擎过滤 + 多因子重排。

整体链路（面试可以直接按这三步讲）：

    候选集 → [召回] 协同过滤算兴趣分 → [过滤] 规则引擎剔除不可选/已修 → [重排] 多因子打分 → TopN

一、为什么用"混合推荐"而不是单一算法
- 纯协同过滤的硬伤是**冷启动**：新课程没人选过就没有相似度，新学生没历史就没向量。
  实测在教务场景里，第一学期新生协同过滤几乎给不出结果。
- 纯规则推荐（按学分缺口/专业匹配打分）没有"个性化"，所有同专业学生推荐结果一样。
- 所以采用 协同过滤（个性化）+ 规则（业务约束与可解释性）**加权融合**，
  既有个性化排序，又保证推荐出来的课"真的能选、选了有用"。

二、相似度计算
- Item-based：两门课的学生评分向量做余弦相似度 —— 回答"选了 A 课的人通常也选 B"；
- User-based：两个学生已修课程评分向量做余弦相似度（取 TopK 邻居）——
  回答"和你水平相近的同学还选了 C"；
- 评分矩阵用 final_score/100 作为显式反馈；只选课没出成绩的记为 0.6 的隐式反馈
  （选了说明有兴趣，但兴趣强度弱于高分通过）。

三、性能
- 相似度矩阵 O(n²) 计算，课程量级（千门）内可接受；
- 矩阵缓存进 Redis，TTL 10 分钟，课程/成绩变更时主动失效；
- 真实生产环境应改为离线（Spark/定时任务）预计算写回 Redis，在线只做查表 + 排序。
"""
from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.redis_client import cache_get, cache_set
from app.models.course import Course, CoursePrerequisite
from app.models.enrollment import Enrollment, Grade
from app.models.enums import CourseType, EnrollmentStatus
from app.models.rule import GraduationRequirement
from app.models.teaching import CourseOffering, Semester
from app.models.user import Student
from app.services.academic import build_academic_state, offering_time_blocks
from app.services.rule_engine import BLOCK, RuleEngine, RuleContext

IMPLICIT_SELECT_SCORE = 0.6  # 只选未出成绩的隐式反馈强度
SIM_CACHE_KEY = "cache:cf:item_sim"
SIM_CACHE_TTL = 600


# ---------------------------------------------------------------------------
# 评分矩阵与相似度
# ---------------------------------------------------------------------------
def build_rating_matrix(db: Session) -> dict[int, dict[int, float]]:
    """返回 {course_id: {student_id: rating}}。"""
    matrix: dict[int, dict[int, float]] = defaultdict(dict)

    grade_rows = db.execute(select(Grade)).scalars().all()
    for g in grade_rows:
        # 取该学生这门课的最高分作为评分
        prev = matrix[g.course_id].get(g.student_id, -1)
        score = min(max(g.final_score, 0), 100) / 100.0
        if score > prev:
            matrix[g.course_id][g.student_id] = score

    enrollment_rows = db.execute(
        select(Enrollment).where(Enrollment.status != EnrollmentStatus.DROPPED)
    ).scalars().all()
    for en in enrollment_rows:
        if en.student_id not in matrix[en.course_id]:
            matrix[en.course_id][en.student_id] = IMPLICIT_SELECT_SCORE

    return {k: dict(v) for k, v in matrix.items()}


def cosine_similarity(a: dict[int, float], b: dict[int, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[i] * b[i] for i in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_item_similarity(matrix: dict[int, dict[int, float]]) -> dict[int, dict[int, float]]:
    """课程-课程相似度矩阵，每门课只保留 Top20 邻居，控制内存与计算量。"""
    cached = cache_get(SIM_CACHE_KEY)
    if cached:
        return {int(k): {int(k2): v2 for k2, v2 in v.items()} for k, v in cached.items()}

    courses = list(matrix.keys())
    sim: dict[int, dict[int, float]] = {}
    for i, ci in enumerate(courses):
        scores: list[tuple[int, float]] = []
        for cj in courses[i + 1:]:
            s = cosine_similarity(matrix[ci], matrix[cj])
            if s > 0.05:  # 相似度过低直接丢弃，避免噪声
                scores.append((cj, round(s, 4)))
        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[:20]  # 只保留 Top20 邻居，控制矩阵规模与内存
        if top:
            sim.setdefault(ci, {})
            for cj, s in top:
                sim[ci][cj] = s
                # 余弦相似度是对称的，反向也写入，后续查询时无需再取一次 transpose
                sim.setdefault(cj, {})[ci] = s

    cache_set(SIM_CACHE_KEY, sim, SIM_CACHE_TTL)
    return sim


# ---------------------------------------------------------------------------
# 协同过滤打分
# ---------------------------------------------------------------------------
def item_cf_score(
    course_id: int,
    user_ratings: dict[int, float],
    sim: dict[int, dict[int, float]],
) -> tuple[float, list[int]]:
    """基于物品的协同过滤：用学生已修课程与候选课程的相似度做加权预测。"""
    if not user_ratings:
        return 0.0, []
    num, den = 0.0, 0.0
    contributors: list[tuple[int, float]] = []
    for rated_course, rating in user_ratings.items():
        s = sim.get(course_id, {}).get(rated_course)
        if s:
            num += s * rating
            den += abs(s)
            contributors.append((rated_course, s))
    if den == 0:
        return 0.0, []
    contributors.sort(key=lambda x: x[1], reverse=True)
    return num / den, [c for c, _ in contributors[:3]]


def user_cf_score(
    student_id: int,
    candidate_course_id: int,
    matrix: dict[int, dict[int, float]],
    top_k: int = 20,
) -> tuple[float, list[int]]:
    """基于用户的协同过滤：找相似同学，看他们在这门课上的平均表现。"""
    my_vector = {cid: ratings[student_id] for cid, ratings in matrix.items() if student_id in ratings}
    if not my_vector:
        return 0.0, []

    neighbors: list[tuple[int, float]] = []
    student_ids = {sid for ratings in matrix.values() for sid in ratings}
    for other in student_ids:
        if other == student_id:
            continue
        other_vector = {cid: ratings[other] for cid, ratings in matrix.items() if other in ratings}
        s = cosine_similarity(my_vector, other_vector)
        if s > 0.1:
            neighbors.append((other, s))
    neighbors.sort(key=lambda x: x[1], reverse=True)
    neighbors = neighbors[:top_k]
    if not neighbors:
        return 0.0, []

    ratings_of_course = matrix.get(candidate_course_id, {})
    num, den = 0.0, 0.0
    contributors: list[tuple[int, float]] = []
    for nid, s in neighbors:
        r = ratings_of_course.get(nid)
        if r is not None:
            num += s * r
            den += abs(s)
            contributors.append((nid, s))
    if den == 0:
        return 0.0, []
    contributors.sort(key=lambda x: x[1], reverse=True)
    return num / den, [c for c, _ in contributors[:3]]


# ---------------------------------------------------------------------------
# 规则打分（多因子）
# ---------------------------------------------------------------------------
def _scope_match(scope: str | None, student: Student, ref: str | None = None) -> bool:
    if not scope:
        return True
    values = {s.strip() for s in scope.split(",") if s.strip()}
    return str(student.major_id) in values


def rule_factor_score(
    db: Session,
    student: Student,
    offering: CourseOffering,
    state,
    requirements: dict[CourseType, float],
    earned_by_type: dict[CourseType, float],
) -> tuple[float, list[str]]:
    """规则侧打分：把"选了对你有没有用"量化。返回 (0-100 分, 推荐理由)。"""
    course = offering.course
    reasons: list[str] = []
    score = 0.0

    # ① 毕业缺口：这类课还差得越多，越该推（权重最高）
    required = requirements.get(course.course_type, 0.0)
    earned = earned_by_type.get(course.course_type, 0.0)
    gap = max(required - earned, 0.0)
    if required > 0:
        gap_ratio = min(gap / required, 1.0)
        score += gap_ratio * 35
        if gap_ratio > 0.5:
            reasons.append(f"该类别（{course.course_type}）仍缺 {gap:g} 学分，修读优先级高")
        elif gap > 0:
            reasons.append(f"可继续补齐 {course.course_type} 学分（剩余 {gap:g}）")
    else:
        score += 12
        reasons.append("超出培养方案要求的拓展课程，可提升综合素质")

    # ② 专业匹配（面向专业开放的课优先）
    if _scope_match(offering.major_scope, student):
        if offering.major_scope:
            score += 12
            reasons.append("面向你所在专业开放")
        else:
            score += 6
    else:
        score -= 10

    # ③ 时间是否与已选课程冲突（不冲突才有意义）
    conflict = False
    for block in offering_time_blocks(offering, course.name):
        if any(block.conflicts_with(occ) for occ in state.time_blocks):
            conflict = True
            break
    if conflict:
        score -= 25
        reasons.append("与已选课程时间冲突，需先调整课表")
    else:
        score += 15

    # ④ 年级适配
    if offering.grade_scope:
        if str(student.enrollment_year) in {g.strip() for g in offering.grade_scope.split(",")}:
            score += 8
            reasons.append("面向你所在年级开设")
        else:
            score -= 10

    # ⑤ 热度（选课率，反映课程口碑，但不能压过毕业缺口）
    if offering.capacity:
        ratio = offering.selected_count / offering.capacity
        score += min(ratio, 1.0) * 12
        if ratio >= 0.8:
            reasons.append(f"热门课程，余量仅 {offering.remaining} 个，建议尽快选")
        elif ratio <= 0.2:
            reasons.append("当前选课人数较少，通过压力相对小")

    # ⑥ 教师信息补全
    if offering.teacher:
        reasons.append(f"授课教师：{offering.teacher.name}（{offering.teacher.title}）")

    return max(min(score, 100.0), 0.0), reasons


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def recommend_courses(
    db: Session,
    student: Student,
    semester_id: int | None = None,
    limit: int = 10,
    cf_weight: float = 0.55,
) -> list[dict]:
    semester = db.get(Semester, semester_id) if semester_id else _current_semester(db)
    if semester is None:
        return []

    state = build_academic_state(db, student, semester)

    # 已修读过的课程（无论是否通过）都不再作为候选，避免推荐"已上过的课"
    attempted_course_ids = set(state.best_score.keys()) | state.selected_course_ids

    offerings = list(db.execute(
        select(CourseOffering)
        .options(
            selectinload(CourseOffering.course),
            selectinload(CourseOffering.teacher),
            selectinload(CourseOffering.semester),
            selectinload(CourseOffering.time_slots),
        )
        .where(CourseOffering.semester_id == semester.id, CourseOffering.is_open.is_(True))
    ).scalars().all())

    candidates = [
        o for o in offerings
        if o.course_id not in attempted_course_ids
        and o.remaining > 0
        and o.course is not None
        and o.course.is_active
    ]
    if not candidates:
        return []

    # ---------- 协同过滤 ----------
    matrix = build_rating_matrix(db)
    sim = compute_item_similarity(matrix)
    user_ratings = {cid: ratings[student.id] for cid, ratings in matrix.items() if student.id in ratings}

    # ---------- 毕业要求 ----------
    requirements = _requirements(db, student.major_id)
    earned_by_type = _earned_by_type(db, student.id)

    engine = RuleEngine.from_db(db, {"max_credits": state.max_credits, "pass_score": settings.PASS_SCORE})
    results: list[dict] = []

    for offering in candidates:
        # 规则引擎过滤：BLOCK 级别不通过的直接剔除，保证"推荐出来的课一定选得上"
        prereqs = db.execute(
            select(CoursePrerequisite)
            .options(selectinload(CoursePrerequisite.prerequisite))
            .where(CoursePrerequisite.course_id == offering.course_id)
        ).scalars().all()
        ctx = RuleContext(
            state=state, offering=offering, course=offering.course,
            prerequisites=list(prereqs), params={},
        )
        ok, rule_results = engine.evaluate(ctx)
        if not ok:
            continue

        item_score, item_src = item_cf_score(offering.course_id, user_ratings, sim)
        user_score, user_src = user_cf_score(student.id, offering.course_id, matrix)
        # 冷启动兜底：协同过滤没给出信号时，用课程热度做先验
        cold_start = item_score == 0 and user_score == 0
        if cold_start and offering.capacity:
            cf_norm = min(offering.selected_count / offering.capacity, 1.0) * 60
        else:
            cf_norm = (item_score * 0.6 + user_score * 0.4) * 100

        rule_score, reasons = rule_factor_score(db, student, offering, state, requirements, earned_by_type)

        final = cf_weight * cf_norm + (1 - cf_weight) * rule_score

        # 推荐理由：把算法结论翻译成人能看懂的话，可解释性是推荐系统落地的关键
        if item_src:
            names = _course_names(db, item_src)
            reasons.insert(0, f"修过《{names[0]}》的同学也常选这门课")
        if user_src and not item_src:
            reasons.insert(0, "与你学习情况相近的同学选修了这门课")
        if cold_start:
            reasons.insert(0, "新开设课程，暂无历史数据，按课程热度推荐")
        for r in rule_results:
            if r.message and r.level != BLOCK and not r.passed:
                reasons.append(r.message)

        results.append({
            "offering_id": offering.id,
            "course_id": offering.course_id,
            "course_code": offering.course.code,
            "course_name": offering.course.name,
            "credits": offering.course.credits,
            "course_type": offering.course.course_type,
            "teacher_name": offering.teacher.name if offering.teacher else None,
            "score": round(final, 2),
            "reason": reasons[:4],
            "cf_score": round(cf_norm, 2),
            "rule_score": round(rule_score, 2),
            "remaining": offering.remaining,
            "time_slots": [
                {
                    "id": s.id, "weekday": s.weekday, "start_section": s.start_section,
                    "end_section": s.end_section, "start_week": s.start_week,
                    "end_week": s.end_week, "weeks_desc": s.weeks_desc,
                }
                for s in offering.time_slots
            ],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def _current_semester(db: Session) -> Semester | None:
    return db.execute(
        select(Semester).where(Semester.is_current.is_(True))
    ).scalar_one_or_none() or db.execute(
        select(Semester).order_by(Semester.start_date.desc())
    ).scalars().first()


def _requirements(db: Session, major_id: int) -> dict[CourseType, float]:
    rows = db.execute(
        select(GraduationRequirement).where(GraduationRequirement.major_id == major_id)
    ).scalars().all()
    return {r.course_type: r.min_credits for r in rows}


def _earned_by_type(db: Session, student_id: int) -> dict[CourseType, float]:
    rows = db.execute(
        select(Grade, Course).join(Course, Course.id == Grade.course_id).where(
            Grade.student_id == student_id, Grade.is_pass.is_(True)
        )
    ).all()
    result: dict[CourseType, float] = defaultdict(float)
    counted: set[int] = set()
    for grade, course in rows:
        if course.id in counted:
            continue
        counted.add(course.id)
        result[course.course_type] += grade.credits
    return dict(result)


def _course_names(db: Session, course_ids: list[int]) -> list[str]:
    if not course_ids:
        return []
    rows = db.execute(select(Course.name).where(Course.id.in_(course_ids))).scalars().all()
    return list(rows)
