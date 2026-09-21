"""学业风险预警模型：风险扫描的产出，管理员/辅导员据此干预。"""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum

from app.db.base import Base, PKMixin, TimestampMixin
from app.models.enums import AlertStatus, RiskLevel, RiskType


class RiskAlert(Base, PKMixin, TimestampMixin):
    __tablename__ = "t_risk_alert"
    __table_args__ = (
        # 同一学生同一类型同一学期只保留一条未处理预警，避免重复扫描刷屏
        Index("idx_alert_student_type_semester", "student_id", "risk_type", "semester_id"),
    )

    student_id: Mapped[int] = mapped_column(ForeignKey("t_student.id", ondelete="CASCADE"), index=True)
    semester_id: Mapped[int | None] = mapped_column(ForeignKey("t_semester.id"), index=True)
    risk_type: Mapped[RiskType] = mapped_column(SAEnum(RiskType, native_enum=False, length=24), index=True)
    risk_level: Mapped[RiskLevel] = mapped_column(SAEnum(RiskLevel, native_enum=False, length=16), index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0, comment="0-100 综合风险分")
    title: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text, comment="触发原因（JSON 数组，可解释）")
    suggestion: Mapped[str | None] = mapped_column(Text, comment="系统给出的干预建议")
    status: Mapped[AlertStatus] = mapped_column(
        SAEnum(AlertStatus, native_enum=False, length=16), default=AlertStatus.OPEN, index=True
    )
    handler_id: Mapped[int | None] = mapped_column(ForeignKey("t_sys_user.id"))
    handle_note: Mapped[str | None] = mapped_column(String(255))
