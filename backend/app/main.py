"""FastAPI 应用入口。

启动流程：
1. 初始化数据库（首次启动自动建库建表 + 写入内置规则配置，方便零配置演示）；
2. 注册统一异常处理器，保证错误响应结构一致；
3. 挂载 /api/v1 路由与 Swagger 文档；
4. 输出启动自检信息（DB / Redis 连通性），避免"起来才发现连不上"。

生产建议：建表改用 Alembic 迁移（见 docs/ARCHITECTURE.md），
本项目的 create_all 仅为降低演示门槛。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.redis_client import redis_available
from app.db.init_db import init_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("正在初始化数据库 %s ...", settings.DB_NAME)
    try:
        init_database()
        logger.info("数据库初始化完成")
    except Exception as exc:
        logger.error("数据库初始化失败：%s", exc)
        logger.error("请检查 .env 中的 DB_* 配置，或先执行 python scripts/init_mysql.py")
    logger.info("Redis 可用性：%s", "正常" if redis_available() else "不可用（已降级为无缓存模式）")
    yield
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "面向高校教务管理与学生学业规划的前后端分离系统后端。\n\n"
        "**核心能力**：登录鉴权（JWT + RBAC）、专业班级管理、学期与开课计划、"
        "智能选课（事务行锁 + 可配置规则引擎）、个人课表、成绩与 GPA 管理、"
        "协同过滤课程推荐、毕业进度分析与学业风险识别。\n\n"
        "**技术栈**：FastAPI + SQLAlchemy 2.0 + MySQL 8.0 + Redis"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# 前后端分离部署，跨域放行（生产应把 allow_origins 收敛到具体域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_PREFIX)


@app.get("/", tags=["系统"], summary="服务信息")
def root():
    return {
        "code": "OK",
        "message": f"{settings.APP_NAME} 后端服务运行中",
        "data": {
            "version": "1.0.0",
            "docs": "/docs",
            "api_prefix": settings.API_PREFIX,
            "redis": redis_available(),
        },
    }


@app.get("/health", tags=["系统"], summary="健康检查")
def health():
    from sqlalchemy import text

    from app.db.session import SessionLocal

    db_ok = True
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        logger.warning("健康检查数据库异常：%s", exc)

    return {
        "code": "OK" if db_ok else "DEGRADED",
        "message": "healthy" if db_ok else "database unavailable",
        "data": {"database": db_ok, "redis": redis_available()},
    }
