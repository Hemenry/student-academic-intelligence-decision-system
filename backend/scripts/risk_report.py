"""风险扫描结果体检脚本：用于验证风险模型的合理性（有没有假阳性/假阴性）。

用法：python scripts/risk_report.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.services import risk_service  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        results = risk_service.scan_students(db, persist=True)

        print(f"命中风险学生数：{len(results)} / 270")
        print("等级分布：", dict(Counter(r["risk_level"] for r in results)))
        print("类型分布：", dict(Counter(f["risk_type"] for r in results for f in r["findings"])))
        print()

        for grade, label in (("26", "2026级（第1学期）"), ("25", "2025级（第3学期）"), ("24", "2024级（第5学期）")):
            sub = [r for r in results if r["student_no"].startswith(grade)]
            dist = dict(Counter(r["risk_level"] for r in sub))
            types = dict(Counter(f["risk_type"] for r in sub for f in r["findings"]))
            print(f"{label}：命中 {len(sub)}/90  等级 {dist}")
            print(f"          类型 {types}")

        print("\n风险最高的 5 名学生：")
        for r in results[:5]:
            print(f"  {r['student_no']} {r['risk_level']}({r['risk_score']})")
            for f in r["findings"]:
                print(f"     - [{f['risk_level']}] {f['title']}")


if __name__ == "__main__":
    main()
