"""种子数据脚本：一键生成可直接演示的完整教务数据。

生成内容：
- 3 个专业 + 每个专业每届 2 个班；
- 管理员 / 教师 / 学生账号（密码统一 123456，方便演示）；
- 课程库（公共必修、专业必修、专业选修、通识选修）+ 先修课依赖；
- 5 个学期（4 个历史学期 + 1 个正在选课的当前学期）；
- 2024/2025 级学生的历史选课与成绩（给协同过滤喂数据）；
- 当前学期的开课计划与排课时间段；
- 一个容量只有 3 人的"抢课班"，用于验证行锁防超卖。

用法：
    python scripts/seed_data.py            # 增量补充（已有数据会跳过）
    python scripts/seed_data.py --reset    # 清空重建（会删除所有业务数据！）
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.init_db import init_database  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.course import Course, CoursePrerequisite  # noqa: E402
from app.models.enrollment import Enrollment, Grade  # noqa: E402
from app.models.enums import (  # noqa: E402
    CourseType,
    EnrollType,
    EnrollmentStatus,
    SemesterStatus,
    UserRole,
)
from app.models.org import ClassGroup, Major  # noqa: E402
from app.models.risk import RiskAlert  # noqa: E402
from app.models.rule import GraduationRequirement  # noqa: E402
from app.models.teaching import CourseOffering, OfferingTimeSlot, Semester  # noqa: E402
from app.models.user import Student, SysUser, Teacher  # noqa: E402
from app.services.grade_service import score_to_grade_point  # noqa: E402

RNG = random.Random(20260916)
DEFAULT_PASSWORD = "123456"

# 排课时间池：(周几, 起始节, 结束节)
SLOT_POOL = [
    (1, 1, 2), (1, 3, 4), (1, 5, 6), (1, 7, 8),
    (2, 1, 2), (2, 3, 4), (2, 5, 6), (2, 7, 8),
    (3, 1, 2), (3, 3, 4), (3, 5, 6), (3, 7, 8),
    (4, 1, 2), (4, 3, 4), (4, 5, 6), (4, 7, 8),
    (5, 1, 2), (5, 3, 4), (5, 5, 6), (5, 7, 8),
]


# ---------------------------------------------------------------------------
# 基础数据定义
# ---------------------------------------------------------------------------
MAJORS = [
    {"code": "CS", "name": "计算机科学与技术", "college": "计算机学院", "total_credits": 140},
    {"code": "SE", "name": "软件工程", "college": "计算机学院", "total_credits": 138},
    {"code": "DS", "name": "数据科学与大数据技术", "college": "数学与统计学院", "total_credits": 130},
]

# (code, name, credits, hours, type, college, major_scope, description)
COURSES = [
    # ---------------- 公共必修 ----------------
    ("PUB001", "大学英语(一)", 3, 48, CourseType.PUBLIC, "外国语学院", None, "大学英语听说读写综合训练，为后续专业英语打基础。"),
    ("PUB002", "大学英语(二)", 3, 48, CourseType.PUBLIC, "外国语学院", None, "在(一)的基础上强化学术英语阅读与写作能力。"),
    ("PUB003", "高等数学A(上)", 5, 80, CourseType.PUBLIC, "数学与统计学院", None, "极限、导数、微分与不定积分的系统训练，工科数学基石。"),
    ("PUB004", "高等数学A(下)", 5, 80, CourseType.PUBLIC, "数学与统计学院", None, "多元函数微积分、级数与常微分方程，考研数学核心内容。"),
    ("PUB005", "线性代数", 3, 48, CourseType.PUBLIC, "数学与统计学院", None, "矩阵、向量空间与特征值，机器学习与图形学的数学基础。"),
    ("PUB006", "概率论与数理统计", 3, 48, CourseType.PUBLIC, "数学与统计学院", None, "随机变量、分布与统计推断，数据分析必备。"),
    ("PUB007", "大学物理", 4, 64, CourseType.PUBLIC, "物理学院", None, "力学与电磁学基础，培养工程建模思维。"),
    ("PUB008", "思想道德与法治", 3, 48, CourseType.PUBLIC, "马克思主义学院", None, "思想政治理论必修课程。"),
    ("PUB009", "体育(一)", 1, 32, CourseType.PUBLIC, "体育学院", None, "体质健康与运动技能基础训练。"),
    ("PUB010", "体育(二)", 1, 32, CourseType.PUBLIC, "体育学院", None, "专项运动技能提升。"),
    ("PUB011", "程序设计基础(C语言)", 4, 64, CourseType.PUBLIC, "计算机学院", None, "从零开始的编程入门课，讲授数据类型、流程控制、函数与指针。"),
    ("PUB012", "离散数学", 3, 48, CourseType.PUBLIC, "计算机学院", None, "集合论、图论与数理逻辑，算法与数据库理论的前置课程。"),
    # ---------------- 计算机/软工 专业必修 ----------------
    ("CS101", "数据结构", 4, 64, CourseType.REQUIRED, "计算机学院", "CS,SE", "线性表、树、图及其经典算法，计算机专业最重要的专业基础课。"),
    ("CS102", "计算机组成原理", 4, 64, CourseType.REQUIRED, "计算机学院", "CS,SE", "从门电路到指令流水线，理解程序如何在硬件上运行。"),
    ("CS103", "操作系统", 4, 64, CourseType.REQUIRED, "计算机学院", "CS,SE", "进程调度、内存管理、文件系统与并发控制。"),
    ("CS104", "计算机网络", 3, 48, CourseType.REQUIRED, "计算机学院", "CS,SE", "TCP/IP 协议栈、路由与网络编程。"),
    ("CS105", "数据库系统原理", 3, 48, CourseType.REQUIRED, "计算机学院", "CS,SE", "关系模型、SQL、索引与事务，本系统的知识来源之一。"),
    ("CS106", "软件工程", 3, 48, CourseType.REQUIRED, "计算机学院", "CS,SE", "需求分析、架构设计、测试与项目管理方法论。"),
    ("CS107", "算法设计与分析", 3, 48, CourseType.REQUIRED, "计算机学院", "CS,SE", "分治、动态规划、贪心与图算法，面试高频考点。"),
    ("CS108", "编译原理", 3, 48, CourseType.REQUIRED, "计算机学院", "CS,SE", "词法/语法分析与代码生成，理解程序语言的实现。"),
    ("CS201", "人工智能导论", 3, 48, CourseType.REQUIRED, "计算机学院", "CS,SE", "搜索、推理与机器学习的概览性课程。"),
    ("CS202", "机器学习", 3, 48, CourseType.REQUIRED, "计算机学院", "CS,SE", "监督/无监督学习算法与模型评估，推荐系统的算法基础。"),
    # ---------------- 数据科学 专业必修 ----------------
    ("DS101", "数据结构与算法", 4, 64, CourseType.REQUIRED, "数学与统计学院", "DS", "面向数据科学场景的算法基础课。"),
    ("DS102", "Python数据分析", 3, 48, CourseType.REQUIRED, "数学与统计学院", "DS", "NumPy/Pandas 数据处理与可视化实战。"),
    ("DS103", "大数据技术基础", 3, 48, CourseType.REQUIRED, "数学与统计学院", "DS", "Hadoop 与 Spark 生态入门，海量数据处理范式。"),
    ("DS104", "统计学习方法", 3, 48, CourseType.REQUIRED, "数学与统计学院", "DS", "统计视角下的机器学习模型推导。"),
    ("DS105", "数据挖掘", 3, 48, CourseType.REQUIRED, "数学与统计学院", "DS", "关联规则、聚类与异常检测，风险识别算法的来源。"),
    ("DS106", "数据库与数据仓库", 3, 48, CourseType.REQUIRED, "数学与统计学院", "DS", "OLTP 与 OLAP 建模差异、维度建模与 ETL。"),
    # ---------------- 专业选修 ----------------
    ("CS301", "Web应用开发", 3, 48, CourseType.ELECTIVE, "计算机学院", "CS,SE", "前后端分离架构、RESTful API 与前端工程化实战。"),
    ("CS302", "移动应用开发", 3, 48, CourseType.ELECTIVE, "计算机学院", "CS,SE", "跨平台移动端开发与调试。"),
    ("CS303", "大数据技术实践", 3, 48, CourseType.ELECTIVE, "计算机学院", "CS,SE", "离线与实时计算链路搭建。"),
    ("CS304", "分布式系统", 3, 48, CourseType.ELECTIVE, "计算机学院", "CS,SE", "一致性、共识算法与分布式事务，高并发系统的理论基础。"),
    ("CS305", "网络安全", 3, 48, CourseType.ELECTIVE, "计算机学院", "CS,SE", "常见攻击手段与防御策略，含 Web 安全实战。"),
    ("CS306", "深度学习导论", 3, 48, CourseType.ELECTIVE, "计算机学院", "CS,SE", "神经网络、CNN/RNN 与 Transformer 入门。"),
    ("DS301", "数据可视化", 2, 32, CourseType.ELECTIVE, "数学与统计学院", "DS", "用图表讲清数据故事。"),
    ("DS302", "推荐系统实战", 3, 48, CourseType.ELECTIVE, "数学与统计学院", "DS", "协同过滤、排序模型与冷启动问题。"),
    # ---------------- 通识选修 ----------------
    ("GEN001", "大学生心理健康", 2, 32, CourseType.GENERAL, "学生工作处", None, "情绪管理与压力应对。"),
    ("GEN002", "创新创业基础", 2, 32, CourseType.GENERAL, "创新创业学院", None, "商业计划与创新思维训练。"),
    ("GEN003", "中国传统文化概论", 2, 32, CourseType.GENERAL, "人文学院", None, "传统文化的思想脉络与现代价值。"),
    ("GEN004", "艺术鉴赏", 2, 32, CourseType.GENERAL, "艺术学院", None, "音乐与美术作品的鉴赏方法。"),
    ("GEN005", "科技文献检索与写作", 2, 32, CourseType.GENERAL, "图书馆", None, "文献检索、论文写作与学术规范。"),
]

# 先修课：(course_code, [(prereq_code, min_score)])
PREREQUISITES = [
    ("CS101", [("PUB011", 60), ("PUB012", 60)]),
    ("CS102", [("PUB011", 60)]),
    ("CS103", [("CS101", 60), ("CS102", 60)]),
    ("CS104", [("CS101", 60)]),
    ("CS105", [("CS101", 60)]),
    ("CS106", [("CS101", 60)]),
    ("CS107", [("CS101", 60), ("PUB012", 60)]),
    ("CS108", [("CS101", 60)]),
    ("CS201", [("PUB006", 60)]),
    ("CS202", [("CS201", 60), ("PUB005", 60)]),
    ("CS301", [("CS105", 60)]),
    ("CS306", [("CS202", 60)]),
    ("DS102", [("PUB011", 60)]),
    ("DS104", [("PUB006", 60), ("PUB005", 60)]),
    ("DS105", [("DS104", 60)]),
    ("DS302", [("DS104", 60)]),
]

SEMESTERS = [
    # (code, name, academic_year, term, 起止, 状态, 是否当前, 选课窗口)
    ("2024-2025-1", "2024-2025学年第一学期", "2024-2025", 1, date(2024, 9, 2), date(2025, 1, 12), SemesterStatus.FINISHED, False),
    ("2024-2025-2", "2024-2025学年第二学期", "2024-2025", 2, date(2025, 2, 24), date(2025, 7, 6), SemesterStatus.FINISHED, False),
    ("2025-2026-1", "2025-2026学年第一学期", "2025-2026", 1, date(2025, 9, 1), date(2026, 1, 11), SemesterStatus.FINISHED, False),
    ("2025-2026-2", "2025-2026学年第二学期", "2025-2026", 2, date(2026, 2, 23), date(2026, 7, 5), SemesterStatus.FINISHED, False),
    ("2026-2027-1", "2026-2027学年第一学期", "2026-2027", 1, date(2026, 9, 7), date(2027, 1, 17), SemesterStatus.SELECTING, True),
]

# 历史修读计划：按学期序号给出要修的课程代码
# 每学期 15~19 学分，8 个学期约可完成培养方案要求，符合真实教务排课节奏
PLAN_2024 = {
    1: ["PUB003", "PUB001", "PUB011", "PUB009", "PUB008", "PUB012"],
    2: ["PUB004", "PUB002", "PUB005", "PUB010", "PUB007", "GEN001"],
    3: ["PUB006", "CS101", "CS102", "CS201", "GEN002", "GEN004"],
    4: ["CS103", "CS104", "CS105", "CS107", "GEN003", "CS302"],
}
PLAN_2025 = {
    1: ["PUB003", "PUB001", "PUB011", "PUB009", "PUB008", "PUB012"],
    2: ["PUB004", "PUB002", "PUB005", "PUB010", "PUB007", "GEN001"],
}
PLAN_DS_2024 = {
    1: ["PUB003", "PUB001", "PUB011", "PUB009", "PUB008", "PUB012"],
    2: ["PUB004", "PUB002", "PUB005", "PUB010", "PUB007", "GEN001"],
    3: ["PUB006", "DS101", "DS102", "DS104", "GEN002", "GEN004"],
    4: ["DS103", "DS105", "DS106", "GEN003", "GEN005", "DS301"],
}
PLAN_DS_2025 = {
    1: ["PUB003", "PUB001", "PUB011", "PUB009", "PUB008", "PUB012"],
    2: ["PUB004", "PUB002", "PUB005", "PUB010", "PUB007", "GEN001"],
}

# 当前学期（2026-2027-1）开课清单：(course_code, capacity, teacher_index)
# 注意最后一个 CQ 班容量只有 3，用于并发抢课验证
CURRENT_OFFERINGS = [
    ("CS106", 60, 0), ("CS108", 50, 1), ("CS202", 45, 0), ("CS201", 60, 2),
    ("CS301", 40, 1), ("CS302", 40, 2), ("CS303", 35, 0), ("CS304", 35, 1),
    ("CS305", 40, 2), ("CS306", 60, 3),
    ("DS103", 45, 3), ("DS105", 45, 2), ("DS106", 40, 3), ("DS301", 50, 1), ("DS302", 40, 0),
    ("GEN005", 80, 3), ("GEN002", 60, 1), ("GEN003", 60, 0),
    # 2026 级新生公共课
    ("PUB003", 90, 0), ("PUB001", 90, 1), ("PUB011", 90, 2), ("PUB009", 90, 3),
    ("PUB008", 90, 1), ("PUB012", 90, 0),
    # 公共必修补充
    ("PUB004", 80, 2), ("PUB005", 80, 3), ("PUB006", 80, 1),
    ("CS101", 60, 0), ("CS102", 60, 1), ("CS103", 60, 2), ("CS104", 60, 3), ("CS105", 60, 0),
]

TEACHERS = [
    ("T1001", "张伟", "教授", "计算机学院"),
    ("T1002", "李娜", "副教授", "计算机学院"),
    ("T1003", "王强", "讲师", "计算机学院"),
    ("T1004", "陈静", "副教授", "数学与统计学院"),
]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def banner(text: str) -> None:
    print(f"\n{'=' * 8} {text} {'=' * 8}")


def reset_database() -> None:
    """清空所有业务数据（保留表结构）。注意删除顺序遵循外键依赖。"""
    from app.db.session import engine

    with engine.begin() as conn:
        conn.execute(delete(RiskAlert))
        conn.execute(delete(Grade))
        conn.execute(delete(Enrollment))
        conn.execute(delete(OfferingTimeSlot))
        conn.execute(delete(CourseOffering))
        conn.execute(delete(CoursePrerequisite))
        conn.execute(delete(GraduationRequirement))
        conn.execute(delete(Student))
        conn.execute(delete(Teacher))
        conn.execute(delete(SysUser))
        conn.execute(delete(ClassGroup))
        conn.execute(delete(Course))
        conn.execute(delete(Semester))
        conn.execute(delete(Major))
    print("已清空业务数据（表结构保留）")


def make_slots(offering_id: int, seed: int, count: int = 2, weeks: str = "1-16") -> list[OfferingTimeSlot]:
    """按种子取时间池，保证同一教学班时间段不重叠。"""
    slots = []
    used: list[tuple[int, int, int]] = []
    idx = seed
    while len(slots) < count and idx < seed + len(SLOT_POOL):
        weekday, s, e = SLOT_POOL[idx % len(SLOT_POOL)]
        if weekday not in {u[0] for u in used}:
            used.append((weekday, s, e))
            start_week, end_week = 1, 16
            slots.append(OfferingTimeSlot(
                offering_id=offering_id, weekday=weekday, start_section=s, end_section=e,
                start_week=start_week, end_week=end_week, weeks_desc=weeks,
            ))
        idx += 1
    return slots


# ---------------------------------------------------------------------------
# 各阶段
# ---------------------------------------------------------------------------
def seed_org(db) -> tuple[dict[str, Major], dict[str, ClassGroup]]:
    banner("专业与班级")
    majors: dict[str, Major] = {}
    for item in MAJORS:
        major = db.execute(select(Major).where(Major.code == item["code"])).scalar_one_or_none()
        if major is None:
            major = Major(**item)
            db.add(major)
            db.flush()
        majors[item["code"]] = major

    classes: dict[str, ClassGroup] = {}
    for grade_year in (2024, 2025, 2026):
        for code, major in majors.items():
            for seq in (1, 2):
                name = f"{major.name[:2]}{str(grade_year)[2:]}{seq:02d}"
                klass = db.execute(
                    select(ClassGroup).where(ClassGroup.name == name, ClassGroup.major_id == major.id)
                ).scalar_one_or_none()
                if klass is None:
                    klass = ClassGroup(
                        name=name, major_id=major.id, grade_year=grade_year,
                        counselor=f"{'王李明赵刘陈杨黄周'[grade_year % 8]}老师",
                    )
                    db.add(klass)
                    db.flush()
                classes[f"{code}-{grade_year}-{seq}"] = klass
    db.commit()
    print(f"专业 {len(majors)} 个，班级 {len(classes)} 个")
    return majors, classes


def seed_users(db, majors: dict[str, Major], classes: dict[str, ClassGroup],
               students_per_class: int) -> dict[str, list[Student]]:
    banner("账号与档案")
    pwd_hash = hash_password(DEFAULT_PASSWORD)  # 统一密码，只做一次哈希，避免 bcrypt 反复计算

    # 管理员
    if db.execute(select(SysUser).where(SysUser.username == "admin")).scalar_one_or_none() is None:
        db.add(SysUser(username="admin", password_hash=pwd_hash, real_name="教务管理员", role=UserRole.ADMIN))
        db.flush()
        print("管理员：admin / 123456")

    # 教师
    teachers: list[Teacher] = []
    for no, name, title, college in TEACHERS:
        user = db.execute(select(SysUser).where(SysUser.username == no)).scalar_one_or_none()
        if user is None:
            user = SysUser(username=no, password_hash=pwd_hash, real_name=name, role=UserRole.TEACHER)
            db.add(user)
            db.flush()
        teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
        if teacher is None:
            teacher = Teacher(user_id=user.id, teacher_no=no, name=name, title=title, college=college)
            db.add(teacher)
            db.flush()
        teachers.append(teacher)
    print(f"教师 {len(teachers)} 位（T1001~T1004 / 123456）")

    # 学生
    surnames = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    given = ["雨泽", "思远", "梓涵", "子轩", "浩然", "欣怡", "雨桐", "诗涵", "俊杰", "嘉怡",
             "宇轩", "若曦", "晨阳", "梦琪", "书航", "雅静", "泽宇", "一诺", "逸辰", "清扬"]
    groups: dict[str, list[Student]] = {"2024": [], "2025": [], "2026": []}

    for grade_year in (2024, 2025, 2026):
        seq_no = (grade_year - 2024) * 1000
        for code, major in majors.items():
            for cls_seq in (1, 2):
                klass = classes[f"{code}-{grade_year}-{cls_seq}"]
                for i in range(students_per_class):
                    seq_no += 1
                    student_no = f"{str(grade_year)[2:]}{code}{cls_seq}{i + 1:02d}"
                    if db.execute(select(Student).where(Student.student_no == student_no)).scalar_one_or_none():
                        continue
                    user = SysUser(
                        username=student_no, password_hash=pwd_hash,
                        real_name=f"{RNG.choice(surnames)}{RNG.choice(given)}", role=UserRole.STUDENT,
                    )
                    db.add(user)
                    db.flush()
                    student = Student(
                        user_id=user.id, student_no=student_no, name=user.real_name,
                        gender=RNG.choice(["M", "F"]), major_id=major.id, class_id=klass.id,
                        enrollment_year=grade_year,
                        phone=f"138{RNG.randint(10000000, 99999999)}",
                        email=f"{student_no}@stu.edu.cn",
                    )
                    db.add(student)
                    db.flush()
                    groups[str(grade_year)].append(student)
        db.commit()
        print(f"{grade_year} 级学生 {len(groups[str(grade_year)])} 人")

    return groups


def seed_courses(db, majors: dict[str, Major]) -> dict[str, Course]:
    banner("课程库与先修关系")
    # major_scope 里写的是专业代码（CS/SE/DS），落库时换成真实的专业 id，
    # 避免专业自增 id 变化导致"是否面向本专业"判断失效
    code_to_id = {code: str(major.id) for code, major in majors.items()}

    def resolve_scope(scope: str | None) -> str | None:
        if not scope:
            return None
        return ",".join(code_to_id[c.strip()] for c in scope.split(",") if c.strip() in code_to_id)

    courses: dict[str, Course] = {}
    for code, name, credits, hours, ctype, college, scope, desc in COURSES:
        course = db.execute(select(Course).where(Course.code == code)).scalar_one_or_none()
        if course is None:
            course = Course(code=code, name=name, credits=credits, hours=hours, course_type=ctype,
                            college=college, major_scope=resolve_scope(scope), description=desc)
            db.add(course)
            db.flush()
        else:
            course.major_scope = resolve_scope(scope)
        courses[code] = course

    for course_code, prereqs in PREREQUISITES:
        course = courses[course_code]
        for pre_code, min_score in prereqs:
            exists = db.execute(
                select(CoursePrerequisite).where(
                    CoursePrerequisite.course_id == course.id,
                    CoursePrerequisite.prerequisite_course_id == courses[pre_code].id,
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(CoursePrerequisite(course_id=course.id, prerequisite_course_id=courses[pre_code].id,
                                          min_score=min_score))
    db.commit()
    print(f"课程 {len(courses)} 门，先修关系 {len(PREREQUISITES)} 组")
    return courses


def seed_graduation_requirements(db, majors: dict[str, Major]) -> None:
    banner("毕业学分要求")
    template = [
        (CourseType.REQUIRED, 0.45),
        (CourseType.ELECTIVE, 0.20),
        (CourseType.PUBLIC, 0.30),
        (CourseType.GENERAL, 0.05),
    ]
    for major in majors.values():
        for ctype, ratio in template:
            credits = round(major.total_credits * ratio / 2) * 2
            exists = db.execute(
                select(GraduationRequirement).where(
                    GraduationRequirement.major_id == major.id,
                    GraduationRequirement.course_type == ctype,
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(GraduationRequirement(major_id=major.id, course_type=ctype, min_credits=credits))
    db.commit()
    print(f"已为 {len(majors)} 个专业配置 4 类学分要求")


def seed_semesters(db) -> dict[str, Semester]:
    banner("学期")
    now = datetime.now()
    result: dict[str, Semester] = {}
    for code, name, year, term, start, end, status, is_current in SEMESTERS:
        sem = db.execute(select(Semester).where(Semester.code == code)).scalar_one_or_none()
        if sem is None:
            sem = Semester(
                code=code, name=name, academic_year=year, term=term, start_date=start, end_date=end,
                status=status, is_current=is_current,
                # 当前学期选课窗口设为"此刻前后"，保证演示时规则引擎放行
                select_start_at=now - timedelta(days=14) if is_current else None,
                select_end_at=now + timedelta(days=21) if is_current else None,
            )
            db.add(sem)
            db.flush()
        result[code] = sem
    db.commit()
    print(f"学期 {len(result)} 个，当前学期 {[c for c, _, _, _, _, _, _, cur in SEMESTERS if cur][0]}"
          f"（选课窗口 {now - timedelta(days=14):%Y-%m-%d} ~ {now + timedelta(days=21):%Y-%m-%d}）")
    return result


def seed_history(db, courses: dict[str, Course], semesters: dict[str, Semester],
                 teachers: list[Teacher], groups: dict[str, list[Student]]) -> None:
    banner("历史选课与成绩")
    plans = {
        ("2024", "CS"): (PLAN_2024, ["2024-2025-1", "2024-2025-2", "2025-2026-1", "2025-2026-2"]),
        ("2024", "SE"): (PLAN_2024, ["2024-2025-1", "2024-2025-2", "2025-2026-1", "2025-2026-2"]),
        ("2024", "DS"): (PLAN_DS_2024, ["2024-2025-1", "2024-2025-2", "2025-2026-1", "2025-2026-2"]),
        ("2025", "CS"): (PLAN_2025, ["2025-2026-1", "2025-2026-2"]),
        ("2025", "SE"): (PLAN_2025, ["2025-2026-1", "2025-2026-2"]),
        ("2025", "DS"): (PLAN_DS_2025, ["2025-2026-1", "2025-2026-2"]),
    }

    offering_cache: dict[tuple[int, int], CourseOffering] = {}
    created_offerings = 0
    created_enrollments = 0
    created_grades = 0

    for (grade, major_code), (plan, sem_codes) in plans.items():
        for term_index, sem_code in enumerate(sem_codes, start=1):
            semester = semesters[sem_code]
            course_codes = plan.get(term_index, [])
            # 该学期该专业的教学班先建好（每个课程一个教学班）
            term_offerings: dict[str, CourseOffering] = {}
            for i, course_code in enumerate(course_codes):
                course = courses[course_code]
                key = (semester.id, course.id)
                offering = offering_cache.get(key)
                if offering is None:
                    existing = db.execute(
                        select(CourseOffering).where(
                            CourseOffering.semester_id == semester.id,
                            CourseOffering.course_id == course.id,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        offering = CourseOffering(
                            course_id=course.id, semester_id=semester.id,
                            teacher_id=teachers[i % len(teachers)].id, class_name="01班",
                            capacity=120, selected_count=0, campus="主校区",
                            classroom=f"{'ABCD'[i % 4]}教学楼{200 + i}",
                            major_scope=course.major_scope, is_open=False,
                            remark="历史学期教学班（已归档）",
                        )
                        db.add(offering)
                        db.flush()
                        for slot in make_slots(offering.id, seed=i * 3 + term_index):
                            db.add(slot)
                        created_offerings += 1
                    else:
                        offering = existing
                    offering_cache[key] = offering
                term_offerings[course_code] = offering

            # 该学期该专业的学生逐一选课并出成绩
            for student in groups[grade]:
                major = db.get(Major, student.major_id)
                if major.code != major_code:
                    continue
                for course_code in course_codes:
                    offering = term_offerings[course_code]
                    course = courses[course_code]
                    exists = db.execute(
                        select(Enrollment).where(
                            Enrollment.student_id == student.id,
                            Enrollment.course_id == course.id,
                            Enrollment.semester_id == semester.id,
                        )
                    ).scalar_one_or_none()
                    if exists:
                        continue

                    enrollment = Enrollment(
                        student_id=student.id, offering_id=offering.id, course_id=course.id,
                        semester_id=semester.id, status=EnrollmentStatus.COMPLETED,
                        enroll_type=EnrollType.NORMAL, credits=course.credits,
                        select_at=datetime.combine(semester.start_date - timedelta(days=15), datetime.min.time()),
                    )
                    db.add(enrollment)
                    db.flush()
                    offering.selected_count += 1
                    created_enrollments += 1

                    # 成绩：大部分学生 70-95 分，少量挂科制造风险样本
                    ability = getattr(student, "_ability", None)
                    if ability is None:
                        ability = RNG.gauss(80, 8)
                        student._ability = ability
                    score = max(min(RNG.gauss(ability, 7), 100), 0)
                    if RNG.random() < 0.06:
                        score = RNG.uniform(38, 59)  # 制造挂科样本
                    score = round(score, 1)
                    usual = round(max(min(score + RNG.uniform(-5, 8), 100), 0), 1)
                    exam = round(max(min(score + RNG.uniform(-8, 5), 100), 0), 1)
                    db.add(Grade(
                        enrollment_id=enrollment.id, student_id=student.id, course_id=course.id,
                        semester_id=semester.id, attempt_no=1, usual_score=usual, exam_score=exam,
                        final_score=score, grade_point=score_to_grade_point(score), credits=course.credits,
                        is_pass=score >= 60, is_retake=False, recorded_at=datetime.combine(
                            semester.end_date, dtime(10, 0)),
                        remark=None,
                    ))
                    created_grades += 1
            db.commit()

    print(f"历史教学班 {created_offerings} 个，选课记录 {created_enrollments} 条，成绩 {created_grades} 条")


def seed_current_offerings(db, courses: dict[str, Course], semesters: dict[str, Semester],
                           teachers: list[Teacher]) -> list[CourseOffering]:
    banner("当前学期开课计划")
    semester = semesters["2026-2027-1"]
    offerings: list[CourseOffering] = []

    for i, (course_code, capacity, teacher_idx) in enumerate(CURRENT_OFFERINGS):
        course = courses[course_code]
        offering = db.execute(
            select(CourseOffering).where(
                CourseOffering.semester_id == semester.id, CourseOffering.course_id == course.id,
                CourseOffering.class_name == "01班",
            )
        ).scalar_one_or_none()
        if offering is None:
            offering = CourseOffering(
                course_id=course.id, semester_id=semester.id, teacher_id=teachers[teacher_idx].id,
                class_name="01班", capacity=capacity, selected_count=0, campus="主校区",
                classroom=f"{'ABCD'[i % 4]}教学楼{100 + i}",
                major_scope=course.major_scope,
                grade_scope=None,
                is_open=True,
                remark=course.description,
            )
            db.add(offering)
            db.flush()
            for slot in make_slots(offering.id, seed=i * 2, count=2):
                db.add(slot)
        offerings.append(offering)

    # 抢课验证专用：容量仅 3 的选修班（选一门无先修要求的通识课，任何专业、任何年级都能选）
    hot_course = courses["GEN004"]
    hot = db.execute(
        select(CourseOffering).where(
            CourseOffering.semester_id == semester.id, CourseOffering.course_id == hot_course.id,
            CourseOffering.class_name == "抢课验证班",
        )
    ).scalar_one_or_none()
    if hot is None:
        hot = CourseOffering(
            course_id=hot_course.id, semester_id=semester.id, teacher_id=teachers[0].id,
            class_name="抢课验证班", capacity=3, selected_count=0, campus="主校区",
            classroom="实验楼501", major_scope=None, is_open=True,
            remark="容量仅 3 人，用于并发选课（行锁防超卖）验证，抢完即止",
        )
        db.add(hot)
        db.flush()
        for slot in make_slots(hot.id, seed=7, count=2):
            db.add(slot)
    offerings.append(hot)

    db.commit()
    print(f"当前学期教学班 {len(offerings)} 个（含 1 个容量 3 的抢课验证班）")
    return offerings


def seed_demo_selections(db, groups: dict[str, list[Student]]) -> None:
    banner("为学生真实走一遍选课流程（验证规则引擎）")
    from app.services.selection_service import select_course

    success, rejected = 0, 0
    samples = (groups["2024"][:12] + groups["2025"][:12])
    for student in samples:
        result = db.execute(
            select(CourseOffering)
            .join(Course, Course.id == CourseOffering.course_id)
            .where(CourseOffering.is_open.is_(True), CourseOffering.class_name == "01班")
            .order_by(func.rand())
            .limit(3)
        ).scalars().all()
        for offering in result:
            try:
                select_course(db, student, offering.id)
                success += 1
            except Exception:
                db.rollback()
                rejected += 1
    print(f"选课成功 {success} 次，被规则拦截 {rejected} 次（拦截是预期行为，说明规则生效）")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成演示种子数据")
    parser.add_argument("--reset", action="store_true", help="清空已有业务数据后重建")
    parser.add_argument("--students-per-class", type=int, default=15, help="每个班级学生数")
    args = parser.parse_args()

    init_database()
    if args.reset:
        reset_database()

    with SessionLocal() as db:
        majors, classes = seed_org(db)
        groups = seed_users(db, majors, classes, args.students_per_class)
        courses = seed_courses(db, majors)
        seed_graduation_requirements(db, majors)
        semesters = seed_semesters(db)
        teachers = list(db.execute(select(Teacher).order_by(Teacher.teacher_no)).scalars().all())
        seed_history(db, courses, semesters, teachers, groups)
        seed_current_offerings(db, courses, semesters, teachers)
        seed_demo_selections(db, groups)

    banner("完成")
    print("""
登录信息（密码统一 123456）：
  管理员  admin
  教师    T1001 / T1002 / T1003 / T1004
  学生    学号即账号，例如 24CS101（2024级计算机1班第1位）

学生账号命名规则：{入学年份后两位}{专业代码}{班号}{序号}
  24CS101 -> 2024级 计算机科学与技术 1班 01号
  25DS205 -> 2025级 数据科学与大数据技术 2班 05号
  26SE110 -> 2026级 软件工程 1班 10号
""")


if __name__ == "__main__":
    main()
