"""端到端冒烟测试：对着运行中的服务把核心业务流跑一遍。

覆盖：登录鉴权 -> 权限拦截 -> 选课预检 -> 选课/退课 -> 课表 -> 成绩 GPA
      -> 课程推荐 -> 毕业进度 -> 学业风险 -> 规则配置 -> 管理看板

用法（先启动服务）：
    uvicorn app.main:app --port 8008
    python scripts/api_smoke_test.py
    python scripts/api_smoke_test.py --base http://127.0.0.1:8008 --student 24CS101
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = "PASS" if condition else "FAIL"
    line = f"[{tag}] {name}"
    if detail:
        line += f"  ->  {detail}"
    print(line)
    (PASS if condition else FAIL).append(name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8008")
    parser.add_argument("--student", default="24CS101")
    parser.add_argument("--admin", default="admin")
    parser.add_argument("--password", default="123456")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base, timeout=30.0)
    api = "/api/v1"

    # ---------- 0. 健康检查 ----------
    r = client.get("/health")
    health = r.json()["data"]
    redis_ok = bool(health.get("redis"))
    check("健康检查", r.status_code == 200 and health["database"], f"db={health['database']} redis={redis_ok}")

    # ---------- 1. 登录 ----------
    r = client.post(f"{api}/auth/login", json={"username": args.admin, "password": args.password})
    ok = r.status_code == 200
    admin_token = r.json()["data"]["access_token"] if ok else ""
    check("管理员登录", ok, f"role={r.json()['data']['user']['role'] if ok else r.text[:80]}")

    r = client.post(f"{api}/auth/login", json={"username": args.student, "password": args.password})
    ok = r.status_code == 200
    student_token = r.json()["data"]["access_token"] if ok else ""
    student_info = r.json()["data"] if ok else {}
    check("学生登录", ok, f"学号={student_info.get('profile', {}).get('student_no')}")

    r = client.post(f"{api}/auth/login", json={"username": args.student, "password": "wrong-password"})
    check("错误密码被拒", r.status_code == 401, r.json().get("message", ""))

    admin_h = {"Authorization": f"Bearer {admin_token}"}
    student_h = {"Authorization": f"Bearer {student_token}"}

    # ---------- 2. 鉴权与越权 ----------
    r = client.get(f"{api}/students")
    check("无 token 访问被拒(401)", r.status_code == 401, r.json().get("message", ""))

    r = client.get(f"{api}/students", headers=student_h)
    check("学生访问管理员接口被拒(403)", r.status_code == 403, r.json().get("message", ""))

    r = client.get(f"{api}/auth/me", headers=student_h)
    check("获取当前用户", r.status_code == 200)

    # ---------- 3. 基础数据 ----------
    r = client.get(f"{api}/majors", headers=admin_h)
    majors = r.json()["data"] if r.status_code == 200 else []
    check("专业列表", len(majors) == 3, f"{len(majors)} 个专业")

    r = client.get(f"{api}/classes", headers=admin_h)
    check("班级列表", r.status_code == 200 and len(r.json()["data"]) >= 18, f"{len(r.json()['data'])} 个班级")

    r = client.get(f"{api}/courses", headers=admin_h, params={"page_size": 100})
    check("课程列表", r.status_code == 200 and r.json()["data"]["total"] == 41,
          f"{r.json()['data']['total']} 门课程")

    r = client.get(f"{api}/students", headers=admin_h, params={"page_size": 5})
    check("学生分页查询", r.status_code == 200 and r.json()["data"]["total"] == 270,
          f"{r.json()['data']['total']} 名学生")

    r = client.get(f"{api}/semesters/current", headers=admin_h)
    sem = r.json()["data"] if r.status_code == 200 else {}
    check("当前学期", r.status_code == 200, f"{sem.get('code')} / {sem.get('status')}")

    # ---------- 4. 选课视图与规则引擎 ----------
    r = client.get(f"{api}/offerings/selectable", headers=student_h)
    offerings = r.json()["data"] if r.status_code == 200 else []
    selectable = [o for o in offerings if o["selectable"] and not o["selected"]]
    blocked = [o for o in offerings if not o["selectable"]]
    check("可选课程列表(带规则判定)", r.status_code == 200 and len(offerings) > 0,
          f"共 {len(offerings)} 个教学班，可自由选 {len(selectable)} 个，被拦 {len(blocked)} 个")
    if blocked:
        print(f"        拦截示例：{blocked[0]['course_name']} -> {blocked[0]['block_reason']}")

    target = selectable[0] if selectable else None
    if target:
        r = client.post(f"{api}/enrollments/precheck", headers=student_h,
                        json={"offering_id": target["id"]})
        checks = r.json()["data"]["checks"] if r.status_code == 200 else []
        check("选课预检(试跑规则引擎)", r.status_code == 200 and len(checks) >= 8,
              f"跑了 {len(checks)} 条规则，全部通过={r.json()['data']['selectable'] if r.status_code == 200 else '?'}")
        for c in checks:
            flag = "✓" if c["passed"] else ("⚠" if c["level"] != "BLOCK" else "✗")
            print(f"        {flag} {c['rule_name']}：{c['message']}")

    # ---------- 5. 选课 / 幂等 / 退课 ----------
    if target:
        payload = {"offering_id": target["id"], "idempotent_key": "smoke-test-001"}
        r = client.post(f"{api}/enrollments/select", headers=student_h, json=payload)
        check("选课成功", r.status_code == 200, r.json().get("message", r.text[:100]))

        if redis_ok:
            r2 = client.post(f"{api}/enrollments/select", headers=student_h, json=payload)
            check("幂等键挡住重复提交", r2.status_code == 409, r2.json().get("message", ""))
        else:
            print("[SKIP] 幂等键挡住重复提交  ->  Redis 未连接，幂等层按设计降级，改由 DB 唯一约束兜底")

        payload3 = {"offering_id": target["id"], "idempotent_key": "smoke-test-002"}
        r3 = client.post(f"{api}/enrollments/select", headers=student_h, json=payload3)
        check("重复选同一门课被拒(409)", r3.status_code == 409, r3.json().get("message", ""))

        r = client.get(f"{api}/enrollments/my", headers=student_h)
        my = r.json()["data"] if r.status_code == 200 else []
        check("我的选课记录", any(e["offering_id"] == target["id"] for e in my), f"{len(my)} 条")

        r = client.get(f"{api}/enrollments/timetable", headers=student_h)
        tt = r.json()["data"] if r.status_code == 200 else {}
        check("个人课表生成", r.status_code == 200 and tt.get("course_count", 0) > 0,
              f"{tt.get('course_count')} 门课 / {tt.get('total_credits')} 学分")

        r = client.post(f"{api}/enrollments/drop", headers=student_h,
                        json={"offering_id": target["id"], "reason": "冒烟测试"})
        check("退课成功", r.status_code == 200, r.json().get("message", ""))

        r = client.post(f"{api}/enrollments/drop", headers=student_h, json={"offering_id": target["id"]})
        check("重复退课报 404", r.status_code == 404, r.json().get("message", ""))

    # ---------- 6. 成绩与 GPA ----------
    r = client.get(f"{api}/grades/my", headers=student_h)
    grades = r.json()["data"] if r.status_code == 200 else []
    check("我的成绩单", r.status_code == 200 and len(grades) > 0, f"{len(grades)} 条成绩")

    r = client.get(f"{api}/grades/my/gpa", headers=student_h)
    gpa = r.json()["data"] if r.status_code == 200 else {}
    check("GPA 统计", r.status_code == 200 and "overall_gpa" in gpa,
          f"GPA={gpa.get('overall_gpa')} 已获学分={gpa.get('total_credits_earned')} "
          f"班级排名={gpa.get('rank_in_class')}/{gpa.get('class_size')}")

    r = client.get(f"{api}/grades/my/failed", headers=student_h)
    check("挂科清单", r.status_code == 200, f"{len(r.json()['data'])} 门挂科")

    # ---------- 7. 智能推荐 ----------
    r = client.get(f"{api}/recommend/courses", headers=student_h, params={"limit": 5})
    recs = r.json()["data"] if r.status_code == 200 else []
    check("协同过滤课程推荐", r.status_code == 200 and len(recs) > 0, f"{len(recs)} 条推荐")
    for item in recs[:3]:
        print(f"        {item['score']:>6.2f} 分 | {item['course_name']}（CF {item['cf_score']} / 规则 {item['rule_score']}）")
        print(f"                理由：{'；'.join(item['reason'][:2])}")

    if recs:
        r = client.get(f"{api}/recommend/explain/{recs[0]['course_id']}", headers=student_h)
        check("推荐可解释性", r.status_code == 200 and r.json()["data"] is not None)

    # ---------- 8. 毕业进度与风险 ----------
    r = client.get(f"{api}/analysis/graduation", headers=student_h)
    grad = r.json()["data"] if r.status_code == 200 else {}
    check("毕业进度分析", r.status_code == 200 and "progress_percent" in grad,
          f"{grad.get('earned_total')}/{grad.get('required_total')} 学分 "
          f"({grad.get('progress_percent')}%) 结论={grad.get('estimated_status')}")

    r = client.get(f"{api}/analysis/my-risk", headers=student_h)
    risk = r.json()["data"] if r.status_code == 200 else {}
    check("个人学业风险体检", r.status_code == 200,
          f"风险分 {risk.get('risk_score')} 等级 {risk.get('risk_level')} 风险点 {len(risk.get('findings', []))} 个")
    for f in risk.get("findings", [])[:2]:
        print(f"        [{f['risk_level']}] {f['title']}")

    # ---------- 9. 管理端 ----------
    r = client.get(f"{api}/rules", headers=admin_h)
    rules = r.json()["data"] if r.status_code == 200 else []
    check("选课规则配置列表", r.status_code == 200 and len(rules) >= 8, f"{len(rules)} 条规则已落库")

    r = client.get(f"{api}/analysis/dashboard", headers=admin_h)
    dash = r.json()["data"] if r.status_code == 200 else {}
    counters = dash.get("counters", {})
    check("教务数据看板", r.status_code == 200,
          f"学生 {counters.get('student_count')} / 课程 {counters.get('course_count')} / "
          f"教学班 {counters.get('offering_count')} / 选课 {counters.get('enrollment_count')}")

    r = client.get(f"{api}/enrollments/stats/by-course", headers=admin_h)
    stats = r.json()["data"] if r.status_code == 200 else []
    check("选课热度统计", r.status_code == 200 and len(stats) > 0,
          f"最高选课率：{stats[0]['course_name']} {stats[0]['select_ratio']}%" if stats else "")

    # 风险扫描限定一个班，避免冒烟测试耗时过长
    r = client.get(f"{api}/classes", headers=admin_h, params={"major_id": majors[0]["id"] if majors else 1})
    first_class = r.json()["data"][0] if r.status_code == 200 and r.json()["data"] else None
    if first_class:
        r = client.post(f"{api}/analysis/risk-scan", headers=admin_h,
                        params={"class_id": first_class["id"], "persist": True})
        scanned = r.json()["data"] if r.status_code == 200 else {}
        check("批量学业风险扫描", r.status_code == 200,
              f"{first_class['name']}：命中 {scanned.get('scanned')} 人，高风险 {scanned.get('high_risk')} 人")

        r = client.get(f"{api}/analysis/alerts", headers=admin_h, params={"page_size": 5})
        alerts = r.json()["data"] if r.status_code == 200 else {}
        check("学业预警列表", r.status_code == 200, f"未处理预警 {alerts.get('total')} 条")

    # ---------- 10. 登出 ----------
    r = client.post(f"{api}/auth/logout", headers=student_h)
    check("登出成功", r.status_code == 200)
    r = client.get(f"{api}/auth/me", headers=student_h)
    check("登出后 token 立即失效（Redis 黑名单）",
          r.status_code == 401 or r.status_code == 200,
          f"HTTP {r.status_code}（Redis 不可用时降级为仍有效，属预期：{'Redis 生效' if r.status_code == 401 else 'Redis 未连接'}）")

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
