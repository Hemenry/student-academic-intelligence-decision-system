"""数据库初始化：建库 -> 建表 -> 写入内置规则配置。

为什么放在代码启动流程里：让 clone 下来的人 `uvicorn app.main:app` 就能跑，
降低演示门槛。正式项目请改用 Alembic 做版本化迁移。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("app.init_db")


def create_database_if_not_exists() -> None:
    """连接 MySQL 服务器（不指定库）执行 CREATE DATABASE IF NOT EXISTS。"""
    from sqlalchemy import create_engine, text

    from app.core.config import settings

    engine = create_engine(settings.server_database_url, future=True)
    with engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{settings.DB_NAME}` "
                f"DEFAULT CHARACTER SET {settings.DB_CHARSET} "
                f"COLLATE {settings.DB_CHARSET}_general_ci"
            )
        )
        conn.commit()
    engine.dispose()


def init_database() -> None:
    from app.core.config import settings

    if settings.database_url.startswith("mysql"):
        create_database_if_not_exists()

    # 导入模型以注册到 Base.metadata
    from app.db.base import Base
    from app.db.session import engine
    import app.models  # noqa: F401  触发所有模型注册

    Base.metadata.create_all(bind=engine)
    logger.info("表结构已就绪：%s 张表", len(Base.metadata.tables))

    seed_default_rules()


def seed_default_rules() -> None:
    """把代码内置的规则写入 t_select_rule，让管理员开箱即可在后台开关/调参。"""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.rule import SelectRule
    from app.services.rule_engine import RULE_REGISTRY

    with SessionLocal() as db:
        existing = {r.rule_key for r in db.execute(select(SelectRule)).scalars().all()}
        created = 0
        for rule in sorted(RULE_REGISTRY.values(), key=lambda r: r.default_priority):
            if rule.rule_key in existing:
                continue
            db.add(SelectRule(
                rule_key=rule.rule_key,
                name=rule.name,
                description="系统内置规则，可在此调整开关与参数",
                params=json.dumps(rule.default_params, ensure_ascii=False),
                priority=rule.default_priority,
                enabled=True,
            ))
            created += 1
        if created:
            db.commit()
            logger.info("已写入 %s 条内置选课规则", created)
