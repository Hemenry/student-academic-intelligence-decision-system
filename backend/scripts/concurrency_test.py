"""并发抢课压测脚本：验证"行锁 + 分布式锁"确实能防超卖。

场景：一个容量只有 3 人的教学班，几十个线程同时抢。
预期结果：恰好 3 人成功，其余全部因满员被拒，且 selected_count 与真实记录数一致，永远是 3。

原理：每个线程独立一个数据库连接与事务，`SELECT ... FOR UPDATE`
让它们在"教学班"这一行上串行排队，读到的一定是前一个事务提交后的最新计数，
因此不会出现"两个人都看到剩 1 个名额"的经典超卖场景。

用法：
    python scripts/concurrency_test.py                          # 自动挑容量最小的教学班
    python scripts/concurrency_test.py --offering-id 42 --threads 60
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.course import Course  # noqa: E402
from app.models.enrollment import Enrollment  # noqa: E402
from app.models.enums import StudentStatus  # noqa: E402
from app.models.teaching import CourseOffering  # noqa: E402
from app.models.user import Student  # noqa: E402
from app.services.selection_service import select_course  # noqa: E402


def pick_offering(offering_id: int | None) -> tuple[int, int, str]:
    with SessionLocal() as db:
        if offering_id:
            offering = db.get(CourseOffering, offering_id)
            if offering is None:
                raise SystemExit(f"教学班 {offering_id} 不存在")
            return offering.id, offering.capacity, offering.course.name if offering.course else ""
        row = db.execute(
            select(CourseOffering)
            .join(Course, Course.id == CourseOffering.course_id)
            .where(CourseOffering.is_open.is_(True))
            .order_by(CourseOffering.capacity)
        ).scalars().first()
        if row is None:
            raise SystemExit("没有可用的教学班，请先执行 python scripts/seed_data.py")
        return row.id, row.capacity, row.course.name


def clean_state(offering_id: int, student_ids: list[int]) -> None:
    """清掉这批学生在该教学班的选课记录，保证每轮测试起点一致。"""
    with SessionLocal() as db:
        for sid in student_ids:
            enrollment = db.execute(
                select(Enrollment).where(
                    Enrollment.student_id == sid,
                    Enrollment.offering_id == offering_id,
                )
            ).scalar_one_or_none()
            if enrollment is not None:
                db.delete(enrollment)
        db.commit()
        # 计数器与真实记录数对齐，排除历史脏数据干扰
        offering = db.get(CourseOffering, offering_id)
        offering.selected_count = db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.offering_id == offering_id, Enrollment.status != "DROPPED"
            )
        ).scalar_one()
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="并发抢课压测")
    parser.add_argument("--offering-id", type=int, default=None, help="目标教学班 id，默认取容量最小的")
    parser.add_argument("--threads", type=int, default=40, help="并发线程数")
    args = parser.parse_args()

    offering_id, capacity, course_name = pick_offering(args.offering_id)

    with SessionLocal() as db:
        students = list(db.execute(
            select(Student).where(Student.status == StudentStatus.ENROLLED).limit(args.threads)
        ).scalars().all())
    if not students:
        raise SystemExit("没有可用学生，请先执行 python scripts/seed_data.py")

    clean_state(offering_id, [s.id for s in students])

    print(f"目标教学班：《{course_name}》 容量 {capacity}，并发线程 {len(students)}")
    print("开始抢课 ...\n")

    success: list[int] = []
    full_rejected = 0
    other_errors: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(students))

    def worker(student: Student) -> None:
        nonlocal full_rejected
        barrier.wait()  # 所有线程就位后同时开抢，制造真实争用
        db = SessionLocal()
        try:
            select_course(db, student, offering_id)
            with lock:
                success.append(student.id)
        except Exception as exc:
            with lock:
                if "已满" in str(exc) or "OFFERING_FULL" in str(exc):
                    full_rejected += 1
                else:
                    other_errors.append(str(exc)[:80])
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(s,)) for s in students]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    with SessionLocal() as db:
        offering = db.get(CourseOffering, offering_id)
        counter = offering.selected_count
        real = db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.offering_id == offering_id, Enrollment.status != "DROPPED"
            )
        ).scalar_one()

    print("=" * 52)
    print(f"耗时              ：{elapsed:.2f}s")
    print(f"抢课成功          ：{len(success)} 人")
    print(f"因满员被拒        ：{full_rejected} 人")
    print(f"因其他原因被拒    ：{len(other_errors)} 人")
    if other_errors:
        from collections import Counter

        for msg, cnt in Counter(other_errors).most_common(3):
            print(f"    - {cnt} 次：{msg}")
    print(f"教学班计数器      ：{counter}")
    print(f"数据库真实记录数  ：{real}")
    print("=" * 52)
    if len(success) <= capacity and counter == real and real <= capacity:
        print(f"结论：未超卖 ✅（成功 {len(success)} <= 容量 {capacity}，计数器与记录数一致）")
    else:
        print(f"结论：出现超卖 ❌（成功 {len(success)}，容量 {capacity}，计数器 {counter}，记录数 {real}）")


if __name__ == "__main__":
    main()
