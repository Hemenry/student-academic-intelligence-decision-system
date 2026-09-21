"""v1 版本路由聚合：main.py 只挂载一个 router，新增模块只改这里。"""
from fastapi import APIRouter

from app.api.v1 import analytics, auth, courses, enrollments, grades, offerings, org, recommend, semesters, students

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(org.router)
api_router.include_router(students.router)
api_router.include_router(courses.router)
api_router.include_router(semesters.router)
api_router.include_router(offerings.router)
api_router.include_router(enrollments.router)
api_router.include_router(grades.router)
api_router.include_router(recommend.router)
api_router.include_router(analytics.router)

__all__ = ["api_router"]
