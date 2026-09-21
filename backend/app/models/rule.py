"""规则与毕业要求模型。

t_select_rule 是**规则引擎的配置源**：每条规则有唯一 key、开关、优先级和参数(JSON)。
好处是"改规则不改代码"——比如把学分上限从 30 调到 28，只改一条数据、清一下缓存即可，
面试里这是很典型的"可配置化/开闭原则"落地。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum

from app.db.base import Base, PKMixin, TimestampMixin
from app.models.enums import CourseType


class SelectRule(Base, PKMixin, TimestampMixin):
    __tablename__ = "t_select_rule"

    rule_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="规则唯一标识")
    name: Mapped[str] = mapped_column(String(64), comment="规则名称")
    description: Mapped[str | None] = mapped_column(String(255))
    params: Mapped[str | None] = mapped_column(Text, comment="规则参数 JSON")
    priority: Mapped[int] = mapped_column(Integer, default=100, comment="越小越先执行")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    @property
    def params_dict(self) -> dict[str, Any]:
        if not self.params:
            return {}
        try:
            return json.loads(self.params)
        except json.JSONDecodeError:
            return {}


class GraduationRequirement(Base, PKMixin, TimestampMixin):
    """专业毕业学分要求：按课程类别拆分最低学分，毕业进度分析据此计算完成度。"""

    __tablename__ = "t_graduation_requirement"
    __table_args__ = (UniqueConstraint("major_id", "course_type", name="uk_major_course_type"),)

    major_id: Mapped[int] = mapped_column(ForeignKey("t_major.id", ondelete="CASCADE"), index=True)
    course_type: Mapped[CourseType] = mapped_column(SAEnum(CourseType, native_enum=False, length=16))
    min_credits: Mapped[float] = mapped_column(Float, comment="该类课程最低学分要求")
