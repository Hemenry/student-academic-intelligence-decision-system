"""智能推荐接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentStudent, DbSession
from app.core.redis_client import cache_get, cache_set
from app.schemas import RecommendOut, Resp
from app.services import recommend_service

router = APIRouter(prefix="/recommend", tags=["智能推荐"])

CACHE_TTL = 300


@router.get("/courses", response_model=Resp[list[RecommendOut]], summary="学生：个性化课程推荐")
def recommend_courses(
    db: DbSession,
    student: CurrentStudent,
    semester_id: int | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    cf_weight: float = Query(default=0.55, ge=0, le=1, description="协同过滤权重，0=纯规则，1=纯CF"),
):
    """返回推荐列表，每条带推荐分与可解释的推荐理由。

    推荐结果缓存 5 分钟：协同过滤要遍历评分矩阵，属于计算型接口，
    而学生的选课/成绩变动并不频繁，缓存收益明显。选课/退课/录成绩时会主动失效缓存。
    """
    cache_key = f"cache:recommend:{student.id}:{semester_id}:{limit}:{cf_weight}"
    cached = cache_get(cache_key)
    if cached:
        return {"code": "OK", "message": "success(缓存)", "data": cached}

    data = recommend_service.recommend_courses(
        db, student, semester_id=semester_id, limit=limit, cf_weight=cf_weight
    )
    cache_set(cache_key, data, CACHE_TTL)
    return {"code": "OK", "message": "success", "data": data}


@router.get("/explain/{course_id}", response_model=Resp[dict], summary="学生：课程推荐依据说明")
def explain(db: DbSession, student: CurrentStudent, course_id: int):
    """推荐可解释性：告诉学生"为什么给你推这门课"，也是消除算法黑箱感的关键。"""
    results = recommend_service.recommend_courses(db, student, limit=50)
    hit = next((r for r in results if r["course_id"] == course_id), None)
    if hit is None:
        return {
            "code": "OK",
            "message": "该课程未进入你的推荐列表（可能已修读、已选或存在硬性条件不满足）",
            "data": None,
        }
    return {
        "code": "OK",
        "message": "success",
        "data": {
            "course_name": hit["course_name"],
            "final_score": hit["score"],
            "collaborative_filtering_score": hit["cf_score"],
            "rule_score": hit["rule_score"],
            "reasons": hit["reason"],
        },
    }
