# 数据库设计

数据库：`student_academic`（MySQL 8.0 / InnoDB / utf8mb4）
共 **15 张表**，全部使用 `t_` 前缀与单数语义命名。

## 一、实体关系总览

```
                    ┌─────────────┐
                    │  t_major    │ 专业（毕业学分/学制挂在专业上）
                    └──────┬──────┘
                           │ 1:N
                    ┌──────▼──────┐
                    │t_class_group│ 班级（专业 + 入学年份）
                    └──────┬──────┘
                           │ 1:N
┌──────────────┐    ┌──────▼──────┐        ┌───────────────────┐
│ t_sys_user   │1:1 │ t_student   │        │   t_teacher       │
│ 登录凭证/RBAC ├────┤ 学籍档案     │        │   教师档案         │
└──────┬───────┘    └──────┬──────┘        └─────────┬─────────┘
       │ 1:1               │                          │ 1:N
       │                   │ 1:N                      │
       │            ┌──────▼──────────────────────────▼──────┐
       │            │        t_course_offering               │
       │            │  教学班（课程+学期+教师+容量+排课）        │
       │            └───┬──────────────────┬─────────────────┘
       │                │ 1:N              │ N:1
       │        ┌───────▼────────┐  ┌──────▼──────┐
       │        │t_offering_time │  │t_semester   │ 学期（选课窗口）
       │        │_slot 上课时间段  │  └──────┬──────┘
       │        └────────────────┘         │ 1:N
       │                                   │
       │            ┌──────────────────────▼──────┐
       └────1:N─────►        t_enrollment          │ 选课记录（软删除）
                    │  UNIQUE(student,course,sem)  │
                    └──────────────┬───────────────┘
                                   │ 1:1
                          ┌────────▼────────┐
                          │   t_grade       │ 成绩（重修保留多次）
                          └─────────────────┘

┌──────────────┐   ┌───────────────────────┐   ┌──────────────┐
│ t_course     │──►│t_course_prerequisite  │   │t_select_rule │
│ 课程库        │1:N│ 先修课关系             │   │ 规则引擎配置  │
└──────┬───────┘   └───────────────────────┘   └──────────────┘
       │ 1:N
┌──────▼────────────────┐      ┌──────────────┐
│t_graduation_requirement│     │ t_risk_alert │ 学业预警
│ 专业分类别学分要求       │      └──────────────┘
└───────────────────────┘
```

## 二、表清单与设计要点

| 表名 | 说明 | 记录数（演示数据） |
| --- | --- | :-: |
| `t_sys_user` | 统一登录凭证（管理员/教师/学生共用），存 bcrypt 哈希 | 275 |
| `t_student` | 学生学籍档案，1:1 关联 sys_user | 270 |
| `t_teacher` | 教师档案 | 4 |
| `t_major` | 专业（毕业总学分、学制、学位） | 3 |
| `t_class_group` | 班级（专业 + 入学年份 + 辅导员） | 18 |
| `t_course` | 课程库（与学期无关的教学大纲层） | 41 |
| `t_course_prerequisite` | 先修课关系（含最低分数） | 21 |
| `t_semester` | 学期（含选课时间窗口） | 5 |
| `t_course_offering` | 教学班（选课的最小单位，容量即库存） | 74 |
| `t_offering_time_slot` | 上课时间段（周几 + 节次 + 周次） | 148 |
| `t_enrollment` | 选课记录 | 3095 |
| `t_grade` | 成绩单 | 3060 |
| `t_select_rule` | 选课规则配置 | 9 |
| `t_graduation_requirement` | 专业分类别学分要求 | 12 |
| `t_risk_alert` | 学业预警 | 30 |

## 三、关键表字段说明

### t_sys_user 用户表
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `username` | varchar(64) UNIQUE | 登录账号（学号/工号） |
| `password_hash` | varchar(128) | bcrypt 哈希，**永不存明文** |
| `role` | varchar(16) | ADMIN / TEACHER / STUDENT，索引 |
| `status` | varchar(16) | ACTIVE / DISABLED |
| `last_login_at` | datetime | 最后登录时间，用于异常登录排查 |

> 设计取舍：不为每个角色建独立登录表。登录鉴权只查一张表、共享同一套认证逻辑；
> 角色差异通过 `t_student` / `t_teacher` 的 1:1 扩展表承载。

### t_course_offering 教学班（选课争用热点）
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `course_id` | int FK | 课程 |
| `semester_id` | int FK | 学期 |
| `teacher_id` | int FK NULL | 授课教师 |
| `capacity` | int | 课容量（"库存"） |
| `selected_count` | int | **已选人数，行锁保护的计数器** |
| `major_scope` | varchar(255) | 面向专业 id，逗号分隔，空=全校 |
| `grade_scope` | varchar(64) | 面向年级，空=不限 |
| `is_open` | tinyint(1) | 是否开放选课 |

联合索引 `idx_offering_semester_course(semester_id, course_id)` 支撑"某学期某课程有哪些班"。

> 为什么把计数器放在这里而不是 `COUNT(*)` 实时统计：
> 选课时要判断"是否满员"，`COUNT(*)` 需要在 enrollment 上做范围统计，锁粒度大、性能差；
> 单独的计数器字段配合行锁，把争用收敛到一行，吞吐量高得多。
> 代价是需要保证计算器与真实记录数一致 —— 退课时同样在行锁下回滚计数。

### t_enrollment 选课记录
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `student_id` / `offering_id` | int FK | 学生 / 教学班 |
| `course_id` / `semester_id` | int FK | **冗余字段** |
| `status` | varchar(16) | SELECTED / DROPPED / COMPLETED（软删除） |
| `enroll_type` | varchar(16) | NORMAL / RETAKE 重修 / MAKEUP 补修 |
| `credits` | float | **学分快照** |

唯一约束：`UNIQUE(student_id, course_id, semester_id)` —— 数据库层兜底"同课重复选"。

> 为什么冗余 course_id / semester_id：
> ① 支撑上面的唯一约束（唯一约束只能建在本表字段上）；
> ② 让"某学期学了哪些课""这门课历史通过率"这类统计免去多表 JOIN。
> 这是典型的**读性能换存储**的取舍，在教务这种读多写少的场景里收益明显。

> 为什么 `credits` 存快照：课程学分未来可能调整（如 3 学分改 2 学分），
> 历史成绩统计必须按当时的学分算，否则已毕业学生的 GPA 会被改动。

> 为什么退课用软删除：保留选课/退课流水，便于审计与反查恶意刷课；
> 退课后重新选课复用同一行记录，不会撞唯一约束。

### t_grade 成绩单
| 字段 | 说明 |
| --- | --- |
| `enrollment_id` UNIQUE | 与选课记录 1:1 |
| `usual_score` / `exam_score` / `final_score` | 平时 / 期末 / 总评 |
| `grade_point` | 绩点（4.0 分制分段映射） |
| `is_pass` | 是否及格（≥60） |
| `attempt_no` / `is_retake` | 第几次修读 / 是否重修 |
| `recorder_id` | 录入人（可追溯） |

> 为什么成绩独立成表而不是塞进 enrollment：
> 选课是**过程数据**、成绩是**结果数据**，生命周期不同。
> 分开后重修不会覆盖历史成绩（`attempt_no` 记录次数），GPA 只取通过的那一次，
> 同一门课"第一次不及格、第二次通过"的完整轨迹得以保留，毕生生成绩单可完整回溯。

### t_select_rule 选课规则
| 字段 | 说明 |
| --- | --- |
| `rule_key` UNIQUE | 规则唯一标识，与代码里的规则类一一对应 |
| `params` TEXT | JSON 参数（如 `{"max_credits": 30, "warn_gpa": 1.5}`） |
| `priority` | 执行顺序，越小越先执行 |
| `enabled` | 开关 |

> 这是"改规则不改代码"的落地载体。管理员把 `credit_limit` 的 `max_credits`
> 从 30 改成 32，清一下缓存即刻生效，不需要发版、不影响正在执行的事务。

### t_risk_alert 学业预警
| 字段 | 说明 |
| --- | --- |
| `student_id` / `semester_id` | 学生 / 学期 |
| `risk_type` / `risk_level` | 五类风险 / 低中高三级 |
| `risk_score` | 0-100 综合风险分 |
| `reason` | JSON 数组，结构化触发原因 |
| `suggestion` | 干预建议 |
| `status` | OPEN / HANDLED / IGNORED |
| `handler_id` / `handle_note` | 处理人 / 处理记录 |

索引 `idx_alert_student_type_semester(student_id, risk_type, semester_id)`
支撑"同一学生同类型同学期只保留一条未处理预警"的 upsert 判重。

## 四、索引设计一览

| 表 | 索引 | 用途 |
| --- | --- | --- |
| t_student | `student_no` UNIQUE、`major_id`、`class_id` | 学号登录、按专业/班级筛选 |
| t_course | `code` UNIQUE、`name`、`course_type` | 课程检索、按类别过滤 |
| t_course_offering | `idx_offering_semester_course` | 选课列表主查询路径 |
| t_offering_time_slot | `idx_slot_weekday_section` | 时间冲突检测 |
| t_enrollment | `uk_student_course_semester` UNIQUE、`idx_enroll_student_semester`、`idx_enroll_offering` | 防重复选课、我的课表、教学班点名 |
| t_grade | `idx_grade_student_semester` | GPA 统计、成绩单查询 |
| t_risk_alert | `idx_alert_student_type_semester` | 预警判重与列表 |

## 五、建库脚本

无需手写 SQL，两种方式任选：

```bash
# 方式一：启动服务自动建库建表（推荐，同时写入内置规则）
python -m uvicorn app.main:app --port 8008

# 方式二：直接跑种子脚本（内部会先调用 init_database）
python scripts/seed_data.py --reset
```

手工等价 SQL：

```sql
CREATE DATABASE IF NOT EXISTS `student_academic`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
```

> 生产环境建议改用 Alembic 做版本化迁移，项目已按 SQLAlchemy 2.0 模型组织，
> `alembic init` 后 autogenerate 即可生成首版迁移脚本。
