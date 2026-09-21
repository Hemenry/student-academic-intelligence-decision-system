# 管理端 / 学生端 逐功能后端实现讲稿

> 面试官问法：「这个项目的管理员端和学生端的每一个功能都是怎么实现的，从后端角度讲一下。」
>
> 这是**最容易答成流水账**的一个问题。下面按"先立框架 → 再分组展开 → 最后给对照表"来组织，
> 所有接口路径、函数名、表名字段都与 `backend/` 代码一致，可直接对照代码讲。

---

## 〇、先立框架：用 30 秒把问题接住

这段是答题的"骨架"，先说出来，面试官就知道你有结构感，而不是背接口：

> 「这个系统后端一共 **63 个业务接口 + 2 个系统接口**，分成 **10 个模块**。
> 但我想先澄清一个前提：**管理端和学生端不是两套后端**。
> 后端只有一套接口，两端的差异只体现在三个地方：
> **① 命中不同的路由**（如 `/offerings` 是排课视角，`/offerings/selectable` 是选课视角）；
> **② 挂不同的权限依赖**（`AdminUser` / `TeacherUser` / `CurrentStudent`）；
> **③ 同一个 service 做不同字段的拼装**。
> 换句话说，**业务逻辑只有一份，两端是同一份逻辑上面的两个视图**——这也是我坚持把逻辑放在 service 层的原因。
> 接下来我按端分组过一遍。」

然后给这张总览表：

| 模块 | 文件 | 接口数 | 主要面向 |
|---|---|:-:|---|
| 认证 | `api/v1/auth.py` | 4 | 两端共用 |
| 组织管理（专业/班级/教师） | `api/v1/org.py` | 9 | 管理端 + 教师 |
| 学生档案 | `api/v1/students.py` | 6 | 管理端 |
| 课程库 | `api/v1/courses.py` | 6 | 管理端 + 教师 |
| 学期 | `api/v1/semesters.py` | 6 | 读共用 / 写管理端 |
| 开课计划 | `api/v1/offerings.py` | 6 | 管理端 + 学生（`selectable`、`{id}`） |
| 选课 | `api/v1/enrollments.py` | 7 | 学生 5 个 / 管理端 2 个 |
| 成绩 | `api/v1/grades.py` | 8 | 学生 3 个 / 教师管理 5 个 |
| 智能推荐 | `api/v1/recommend.py` | 2 | 学生端 |
| 学业分析 + 规则配置 | `api/v1/analytics.py` | 9 | 学生 2 个 / 管理端 7 个 |
| 系统 | `main.py` | 2 | `GET /`、`GET /health` |
| **合计** | | **65** | 15 张表 |

---

## 一、公共底座：两端所有功能都吃到的三层机制

先讲底座，后面每个功能都能省掉重复解释。

### 1.1 鉴权与角色守卫（`core/deps.py`）

| 依赖 | 校验内容 | 用在哪些功能 |
|---|---|---|
| `CurrentUser` | 解析 `Authorization: Bearer` → JWT 解码 → 过期/无效判定 → **Redis 黑名单校验** → 用户存在且 `ACTIVE` | 全部已登录接口 |
| `AdminUser` | 再要求 `role == ADMIN` | 所有写操作（增删改、开/关选课、风险扫描、规则改参） |
| `TeacherUser` | 要求 `role in (ADMIN, TEACHER)` | 所有查询、成绩录入、预警处理 |
| `CurrentStudent` | 要求 `role == STUDENT`，并**用 `user_id` 反查学生档案** | 学生端全部接口 |

**这里有两句必须说的话：**

1. **学生端接口一律不接受前端传 `student_id`。** 比如"我的成绩"是 `GET /grades/my` 而不是 `GET /grades?student_id=5`。
   传 5 能看自己、改成 6 就能看别人，这是典型的 IDOR 越权。原则是
   **权限校验依赖服务端身份，不依赖客户端参数**。
2. **前端路由守卫（`meta.roles`）只是体验层，真正的安全边界在这里。**
   面试官如果问"前端不做校验吗"，答案就是这句。

### 1.2 统一响应与全局异常（`core/exceptions.py`）

所有接口返回 `{code, message, data}`，由 5 个全局处理器兜住所有异常路径：

| 处理器 | HTTP | code | 说明 |
|---|:-:|---|---|
| `BizError` 及子类 | 400 / 401 / 403 / 404 / 409 | 业务码（如 `ALREADY_SELECTED`、`MAJOR_IN_USE`） | 业务异常自带语义化 code，前端可精细化提示 |
| `RequestValidationError` | 422 | `VALIDATION_ERROR` | **把字段名拼进 message**（"参数校验失败：status ..."），否则前端只看到一句笼统报错 |
| `IntegrityError` | 409 | `DB_INTEGRITY_ERROR` | 唯一约束/外键冲突兜底 |
| `SQLAlchemyError` | 500 | `DB_ERROR` | 数据库层错误统一话术，不泄露 SQL |
| `Exception` | 500 | `INTERNAL_ERROR` | 最后兜底，保证**永远是结构一致的 JSON**，不会给前端返回 HTML 堆栈 |

### 1.3 原子性与事务边界

约定：**一个 service 方法 = 一个事务**。需要主键但还不能提交时用 `db.flush()` 拿 id，
绝不提前 `commit()`。这条规则在"新增学生"和"新增开课计划"两个功能里是硬性要求（下面会讲）。

---

## 二、管理端逐功能（10 个页面）

### 2.1 专业管理 `Majors.vue` → `/majors`

| 接口 | 实现要点 |
|---|---|
| `GET /majors` | 按 `Major.code` 排序返回，供下拉框和列表共用 |
| `POST /majors` | **先查 code 是否已存在**再插入（业务错误码 `MAJOR_CODE_EXISTS`）；数据库唯一索引是最后防线，冲突时被 `IntegrityError` 处理器兜成 409 |
| `PUT /majors/{id}` | 取实体 → 逐字段 `setattr`（整对象覆盖语义，不是 patch） |
| `DELETE /majors/{id}` | **引用检查**：`count(Student where major_id=?)`，有人就拒绝（`MAJOR_IN_USE`，提示"该专业下还有 N 名学生"） |

**要讲的设计取舍（这里要主动承认一个缺口，反而是加分项）**：

设计意图是"**被引用即拒绝**"——教务数据里专业下挂着学生，级联删掉就是静默数据丢失。
但实现上**只拦了学生这一种引用**：`t_class_group.major_id` 建表时是
`ondelete="CASCADE"`，ORM 层 `Major.classes` 也配了 `cascade="all, delete-orphan"`，
`t_graduation_requirement.major_id` 同样是 CASCADE。

所以准确的说法是：

> 「删除专业时我拦住了"专业下有学生"，但**班级和毕业学分要求配置是级联删除的**。
> 这是个已知缺口：一个没有学生、但还有班级和培养方案配置的专业，删掉会连带清空班级
> 和毕业要求。更严谨的做法是把班级数、毕业要求数一并纳入引用检查。
> 我当时选择简单校验是因为教务流程上专业删除本来就是低频且需要审批的操作，
> 但**从数据安全的角度，这个校验应该是完整的**——现在我知道要补哪几项。」

> **别在面试里说"所有删除都是被引用即拒绝"，代码不是这样。** 按上面这个口径讲，
> 展示的是"我知道自己的边界在哪"，比一个被追问就崩的说法安全得多。

### 2.2 班级管理 `Classes.vue` → `/classes`

| 接口 | 实现要点 |
|---|---|
| `GET /classes` | 支持 `major_id` / `grade_year` 筛选；**两条批量查询做装配**：一次查全部专业得到 `major_map`，一次 `group by class_id` 得到各班级人数 `counts`，再拼 `major_name` / `student_count` |
| `POST /classes` | 专业存在性校验 + **同专业内名称唯一**校验（`CLASS_EXISTS`） |
| `PUT /classes/{id}` | 同上整对象覆盖 |
| `DELETE /classes/{id}` | `count(Student where class_id=?)` → 有人则 `CLASS_IN_USE` 拒绝 |

这里有个可以主动提的点：**列表接口要展示"班级人数""所属专业名"这类跨表字段时，
我的做法是先批量查成 map，再在内存里拼**，而不是循环里逐行查。
这就是最朴素的 N+1 治理，两行代码的事，但决定了列表接口是 3 条 SQL 还是 2N+1 条。

### 2.3 学生管理 `Students.vue` → `/students`

| 接口 | 实现要点 |
|---|---|
| `GET /students` | 5 个筛选条件（`keyword` 走姓名/学号 `LIKE`、`major_id`、`class_id`、`grade_year`、`status`）+ 分页。**`total` 用 `count()` over `stmt.subquery()` 复用同一套 where**，避免"筛选了但总数是全量"的经典 bug |
| `GET /students/{id}` | 详情，附带专业名/班级名 |
| `POST /students` | **账号与档案同事务创建**（核心，见下） |
| `PUT /students/{id}` | `model_dump(exclude_none=True)` 做部分更新，不传的字段不动 |
| `POST /students/{id}/reset-password` | 默认重置为 `123456`，bcrypt 重新哈希后覆盖 |
| `DELETE /students/{id}` | 档案和 `t_sys_user` 账号**一起删**，不留孤儿账号 |

**`POST /students` 的实现链路（这个可以讲深）：**

```
校验专业存在 → 校验班级存在 → 校验学号唯一 → 校验登录名未被占用
   ↓
db.add(SysUser(username, hash_password(pwd), role=STUDENT))
db.flush()          # ← 关键：先拿到 user.id，但事务还没提交
   ↓
db.add(Student(user_id=user.id, ...))
db.commit()         # ← 一次提交，账号与档案同生共死
```

为什么必须 `flush` 而不是 `commit`：如果先提交账号再建档案，
第二步失败就会留下"**有账号但没档案**"的脏数据——这种人能登录，但登录后所有学生接口
都会报 `PROFILE_MISSING`。反过来先建档案后建账号，就是"**有档案登不上**"。
用 `flush` 把两者绑在同一个事务里，要么全成、要么全不成。

### 2.4 课程库 `Courses.vue` → `/courses`

| 接口 | 实现要点 |
|---|---|
| `GET /courses` | `keyword`（名称/代码模糊）+ `course_type` 筛选 + 分页；**先调用 `_prereq_name_map()` 用一条 join 把所有课程的先修课名查出来**，再逐条拼装 |
| `GET /courses/{id}` | `selectinload(Course.prereq_links).selectinload(CoursePrerequisite.prerequisite)` —— **两级预加载**，一次拿全课程 + 先修关系 + 先修课实体 |
| `POST` / `PUT` | code 唯一校验；`PUT` 整对象覆盖 |
| `DELETE /courses/{id}` | `count(CourseOffering where course_id=?)`，有开课记录则拒绝（`COURSE_IN_USE`），报错文案直接引导"可改为停用" |
| `PUT /courses/{id}/prerequisites` | **整表覆盖式配置**：一个事务内先 `DELETE` 全部旧关系再逐条 `INSERT`，并校验「先修课不能是自己」（`SELF_PREREQUISITE`）和先修课存在性 |

**先修课为什么用"整表覆盖"而不是增量增删**：管理员在页面上是勾选一组先修课然后保存。
如果做增量 diff，中途失败会留下"删了一半、加了一半"的中间态。
先删后插在一个事务里，外部永远只看到旧集合或新集合，**没有中间态**。

**这里有个真实的踩坑可以讲**：ORM 关系原本叫 `Course.prerequisites`，
和响应模型 `CourseOut.prerequisites` **同名**，Pydantic 的 `from_attributes` 会把 ORM 对象
当成出参去校验 → 列课程接口直接 500。改名为 `prereq_links` 后正常。
教训是**序列化字段名和 ORM 关系名要主动错开**。

### 2.5 学期管理 `Semesters.vue` → `/semesters`

| 接口 | 实现要点 |
|---|---|
| `GET /semesters` | **读接口对所有登录角色开放**，一次 `group by semester_id` 统计各学期开课数拼 `offering_count` |
| `GET /semesters/current` | 优先 `is_current=True`，没有则回退最近一个学期 |
| `POST` / `PUT` | 日期区间校验（`end > start`）+ code 唯一 + **"当前学期"全局唯一** |
| `POST /{id}/open-selection` | 状态切到 `SELECTING`，可同时设置 `select_start_at` / `select_end_at` |
| `POST /{id}/close-selection` | 状态切回 `ONGOING` |
| 权限 | 读接口 `CurrentUser`（任何角色），写接口 `AdminUser` |

**"当前学期唯一"的实现**：设置 `is_current=True` 时，同事务里执行
`UPDATE t_semester SET is_current=0 WHERE id != 本次 id`。
不这么做就会出现两个"当前学期"，`select( Semester ).where(is_current)` 直接
`MultipleResultsFound` 崩掉——所有依赖当前学期的功能（课表、推荐、风险扫描）全部连带失效。

**为什么 `/semesters` 的读权限要对所有角色放开**：原本只给了教师/管理员，
结果学生端「我的成绩」「我的课表」要按学期筛选时直接 403。
判断依据是**这个资源有没有敏感信息**：学期名称、起止日期没有，所以读放开、写收紧。

**「开启选课」为什么不是简单改个标志位**：`Semester.status` 会被规则引擎的
`SemesterWindowRule` 直接读取（`PLANNING` 未开放、`SELECTING` 放行、`ONGOING/FINISHED` 已截止）。
所以管理端点一下按钮，**学生端选课立刻生效或被拦**，全程不用发版。

### 2.6 开课计划 `Offerings.vue` → `/offerings`

| 接口 | 实现要点 |
|---|---|
| `GET /offerings` | 排课视角：`semester_id` / `course_id` / `course_type` / `keyword` / `only_open` + 分页；`_load_offerings_stmt()` 统一预加载 course/teacher/semester/time_slots，`_base_out()` 统一装配（含 `remaining` 余量） |
| `POST /offerings` | 课程/学期存在性 → **排课自冲突校验** → `flush` 拿 id → 先删后插时间段 → 一次 commit |
| `PUT /offerings/{id}` | **容量不能小于已选人数**（`CAPACITY_TOO_SMALL`）；`time_slots` 传了才替换 |
| `DELETE /offerings/{id}` | `selected_count > 0` 拒绝（`OFFERING_IN_USE`），文案引导"请先关闭选课而不是删除" |

**排课自冲突校验（`_check_time_slot_self_conflict`）**：同一个教学班录入的多个时间段之间也不允许重叠。
用的是和规则引擎完全一样的区间重叠判定：

```python
if a.weekday == b.weekday and not (a.end_section < b.start_section or b.end_section < a.start_section):
    if not (a.end_week < b.start_week or b.end_week < a.start_week):
        raise BizError("排课时间段自相冲突：...", code="SLOT_SELF_CONFLICT")
```

**"容量不能小于已选人数"这条校验为什么必须加**：容量是超卖判定的分母。
管理员把容量从 60 改成 40，如果班里已经有 55 个人，后续任何一个学生退课都会让
`selected_count` 逻辑混乱，而且再没人能选进来。**管理端的写操作必须维护并发控制依赖的不变量**——
这句话可以直接作为亮点说出来。

**删除的取舍也一样**：已有学生选课的教学班不给删，只能"关闭选课"。
因为 `t_enrollment` 有外键指过来，物理删掉会破坏历史选课和成绩记录。

### 2.7 成绩录入 `GradeEntry.vue` → `/grades/*`

| 接口 | 实现要点 |
|---|---|
| `PUT /grades/record` | 单条录入，走 `grade_service.record_grade()` |
| `PUT /grades/batch-record` | 批量录入，**逐条独立事务语义** |
| `GET /grades/offering/{id}/roster` | 教学班花名册（含已录成绩） |
| `GET /grades/stats/course/{id}` | 课程成绩分析 |
| `GET /grades/stats/class-rank` | 班级排名 |

**`record_grade()` 的实现链路**：

1. 校验选课记录存在，且状态不是 `DROPPED`（退课的不能录成绩）；
2. 算总评：`final_score` 传了就用它；只用平时分或只用期末分就按那一项计；两项都有则
   `平时 × 权重 + 期末 × (1-权重)`；
3. 总评必须在 0–100（否则 400）；
4. `is_pass = total >= settings.PASS_SCORE`（60）；
5. **`attempt_no = count(该生该课历史成绩) + 1`**，同时 `is_retake = attempt_no > 1`；
6. `grade_point = score_to_grade_point(total)`，4.0 制**表驱动**分段映射；
7. **把 `enrollment.status` 置为 `COMPLETED`** —— 出成绩即视为完成修读。

第 5 步是"选课表与成绩表分开"这个设计落地的地方：因为有 `attempt_no`，
"第一次 52 分、第二次 78 分"的完整轨迹都留着，重修不会覆盖历史。

**批量录入为什么不做整批事务**：

```python
for item in payload.items:
    try:
        grade_service.record_grade(...)   # 内部自带 commit
        success += 1
    except Exception as exc:
        db.rollback()                     # 只回滚这一条
        failed.append({"enrollment_id": item.enrollment_id, "error": str(exc)})
return {"success": success, "failed": failed}
```

老师一次录几十条，如果有一条学号对不上就整批回滚，他要重录 60 条。
**"部分成功"在教务场景里是比"事务原子性"更重要的产品需求**，
返回结构里明确给出失败清单，前端可以逐条提示。

**课程成绩分析**是纯内存聚合：平均分、最高/最低、及格率、五档分布（90-100 / 80-89 / 70-79 / 60-69 / 0-59）。
一次把该课程所有 `Grade` 查出来算，没有落库统计表——**在这个数据量级下不必要**，
面试官问"数据量大了怎么办"就答"加统计表或走离线任务"。

### 2.8 选课统计 `EnrollStats.vue` → `/enrollments` + `/enrollments/stats/by-course`

| 接口 | 实现要点 |
|---|---|
| `GET /enrollments` | 管理端查选课流水：`semester_id` / `offering_id` / `student_id` / `class_id` / `status` + 分页 |
| `GET /enrollments/stats/by-course` | 选课热度排行：join offering + course + semester，算 `select_ratio = selected_count/capacity`，按热度倒序 |

`GET /enrollments` 里有个细节值得讲：`Enrollment` 表只有 `student_id`，
但页面要显示学号和姓名。做法是**先取本页的学生 id 集合，一次 `IN` 查询构建 `student_map`**，
再在内存里补字段——**分页之后再批量补查**，SQL 条数是常数级而不是 N+1。

`class_id` 筛选要注意：它不在 `Enrollment` 上，所以查询是
`join(Student).where(Student.class_id == ?)`，用 join 而不是子查询，让优化器走索引。

`stats/by-course` 的定位是**帮你做决策的数据**：选课率 95% 的班该考虑加开，
选课率 5% 的班该考虑撤并。教务处的真实工作流就是这个。

### 2.9 规则配置 `Rules.vue` → `/rules`

| 接口 | 实现要点 |
|---|---|
| `GET /rules` | 按 `priority` 返回 `t_select_rule` 全部配置；**库里一条都没有时，返回代码里的内置规则（id 用负数区分）** |
| `PUT /rules/{id}` | 改 `enabled` / `params`，commit 后**清推荐与开课缓存** |

这两个接口是整个"可配置化"的落地形态，能讲的东西最多：

**① 配置合并的优先级（`RuleEngine.from_db`）**

```
最终参数 = 规则类的 default_params
          ← 被数据库 row.params_dict 覆盖
          ← 被调用时传入的 extra_params 覆盖（如本次的 max_credits、pass_score）
```

三层覆盖的设计意图：**代码给默认值（保证能跑）、数据库给运营值（管理端可调）、
调用方给上下文值（同一条规则在不同场景取不同上下文）**。
另外配置表里存在但代码未实现的 `rule_key` 会被**安全跳过**，不会因为脏配置把选课打挂。

**② 为什么要有"库里没配置就回退内置规则"**

如果 `t_select_rule` 是空表，严格按配置执行就意味着**一条规则都不跑** —— 所有课都能选，
学分上限、时间冲突全部失效。这是最危险的一种"配置驱动"实现方式。
所以加了兜底：**配置缺失时回退到代码内置的 9 条规则**，宁可严格也不能失效。

**③ 改一条规则要清哪些缓存**

```python
cache_delete_prefix("cache:recommend")
cache_delete_prefix("cache:offering")
```

因为推荐结果和开课列表里都含"能不能选"的判断结果，规则一变，这些缓存全部失效。
**这就是"缓存要与它依赖的数据同生命周期"**——我拆不出更细的粒度，
就用前缀整体删，宁可多删不可脏读。

**④ 一个能直接讲的产品例子**

毕业选课高峰想把学分上限从 30 调到 32：管理员在 `Rules.vue` 把 `credit_limit` 的
`max_credits` 改成 32 → 保存 → 学生端下一次选课校验立刻按新阈值执行。
**全程不研发版、不影响正在进行的事务**。这就是"把业务策略从代码搬进配置"的价值。

### 2.10 学业预警处理 `Alerts.vue` → `/analysis/*`

| 接口 | 实现要点 |
|---|---|
| `POST /analysis/risk-scan` | 批量扫描（可按班级/专业），`persist=true` 时落库 |
| `GET /analysis/alerts` | 预警列表：按类型/等级/状态/班级筛选 + 分页，按 `risk_score` 倒序 |
| `POST /analysis/alerts/{id}/handle` | 写 `status` / `handler_id` / `handle_note` |
| `GET /analysis/student/{id}/report` | 单个学生画像：GPA 统计 + 毕业进度 + 风险明细 |
| `GET /analysis/dashboard` | 看板：全局计数器 + 风险分布（两个 `group by` 聚合） |

**`scan_students()` 的实现链路**：

```
筛出 ENROLLED 学生（可按 class_id / major_id 收窄）
   ↓ 逐个 analyze_student()（五维打分）
   ↓ persist 时：
      ├─ _upsert_alert()         同生+同类型+同学期+状态 OPEN → UPDATE，否则 INSERT
      └─ _resolve_stale_alerts() 本轮没再触发的 OPEN 预警 → 自动置 IGNORED
   ↓ 按 risk_score 倒序返回
```

**幂等落库（`_upsert_alert`）**：为什么是 update 而不是 insert——
每天凌晨跑一次扫描，如果每次都 insert，辅导员第二天打开看到的是几十条重复预警，
功能直接废掉。判重键是 `student_id + risk_type + semester_id + status=OPEN`。

**预警闭环（`_resolve_stale_alerts`）**——这是我认为设计上最值得讲的一处：

```python
for alert in stale:
    if alert.risk_type in triggered:
        continue
    alert.status = AlertStatus.IGNORED
    alert.handle_note = "系统自动复查：本次扫描该风险指标已恢复正常，自动关闭"
```

学生重修通过之后，上一条挂科预警如果一直挂在头上，预警列表就失去可信度。
所以**每轮扫描同时负责"开新预警"和"关旧预警"**，状态机是闭环的。
另外处理过的记录（`HANDLED`）不参与判重，下次再触发会新开一条，
这样能统计"**复发**"，辅导员能看到"这个学生是反复出问题的"。

**`GET /analysis/student/{id}/report` 为什么要单独做一个接口**：它把三块数据合成一份"学生画像"。
辅导员找学生谈话前打开这一页就够了，不用在成绩、毕业进度、预警三个页面之间来回切。
**这是从真实使用场景反推出来的接口，不是按表设计的。**

---

## 三、学生端逐功能（7 个页面）

### 3.1 首页 `Home.vue`

平台自身不新增接口，而是**并行聚合**三块现有能力：学业概览（`/grades/my/gpa`）、
本学期课表（`/enrollments/timetable`）、风险体检摘要（`/analysis/my-risk`）。
设计上刻意不给首页做专属后端接口——**首页是编排层，不该产生新的业务逻辑**。

### 3.2 智能选课 `SelectCourse.vue` → 4 个接口

这是学生端的核心，也是整个项目的技术核心。四个接口分工明确：

| 接口 | 作用 | 实现 |
|---|---|---|
| `GET /offerings/selectable` | 可选课程列表，**每一条都带"能不能选 + 为什么"** | 一次装配快照 + 一次加载规则 + 批量先修课 map，循环内跑 `engine.evaluate()` |
| `POST /enrollments/precheck` | 试点选课（不写库） | `evaluate_offering()` 返回逐条规则结果 |
| `POST /enrollments/select` | 真正选课 | `selection_service.select_course()` 三重防线 |
| `POST /enrollments/drop` | 退课 | 行锁下回滚计数器 |

**`GET /offerings/selectable` 的关键设计**：列表接口**也做完整规则校验**。
如果只在提交时才校验，学生要点进去、填写、提交、失败、再试——试错式体验。
这里对学生本人只做**一次** `build_academic_state`，然后对 return 的每个教学班
复用同一个快照跑规则，返回：

```python
data["selected"]      = offering.course_id in state.selected_course_ids
data["selectable"]    = ok                                    # 只看 BLOCK 级
data["block_reason"]  = blocking[0].message if blocking else None   # 第一条硬性拦截原因
data["warnings"]      = [r.message for r in results if not r.passed and r.level != BLOCK]
```

**`select_course()` 的完整链路**（这段是全场重点，建议按顺序讲）：

```
① Redis 幂等键    SET NX EX 60  (select:idem:{sid}:{oid}:{key})
      挡住双击/网络重试。Redis 挂了 → 降级，交给 DB 唯一约束兜底

② Redis 分布式锁  lock:offering:{id}，SET NX PX 5000ms，等 2s
      SET NX（不覆盖）→ PX 保证超时自动释放 → 释放时 Lua 校验持有者再 DEL
      目的：多实例部署时同一教学班的请求在入口排队，降低 DB 锁争用

③ MySQL 事务（正确性只押在这一层）
   BEGIN
     SELECT t_student        WHERE id=? FOR UPDATE   ← 先锁学生行
     SELECT t_course_offering WHERE id=? FOR UPDATE   ← 再锁教学班行（拿最新 selected_count）
     SELECT t_enrollment  查是否已有记录
        已选未退 → 直接 409 ALREADY_SELECTED（不做规则判定）
     规则引擎全量校验 → 不通过 → 400 RULE_REJECTED + 前 3 条原因
     容量再确认 selected_count >= capacity → 409 OFFERING_FULL
     写记录：有 DROPPED 旧记录 → 复用该行置回 SELECTED（唯一约束限制）
             没有 → INSERT
     UPDATE selected_count = selected_count + 1
   COMMIT
      ↓
   兜底：UNIQUE(student_id, course_id, semester_id)

④ 清缓存：cache:offering* + cache:recommend:{sid}*
⑤ 死锁/锁等待超时会话（1213/1205）回滚重试，最多 3 次
```

**四个"为什么"，面试官大概率会追问，答案要脱口而出：**

| 追问 | 回答 |
|---|---|
| 为什么必须 `FOR UPDATE`，普通 SELECT 不行？ | RR 隔离级别下普通 SELECT 是**快照读**，整个事务看到的值不变。读到 59、别人提交成 60，我基于 59 算出的 60 就是超卖。`FOR UPDATE` 是**当前读 + 排他锁**，一次解决"读最新"和"串行化" |
| 为什么还要锁学生行，只锁教学班不行？ | 学生同时提交两门**时间冲突**的课，两个事务锁的是两个不同教学班行，互不阻塞，各自的冲突检测都通过 → 课表撞课。锁学生行把同一学生的选课**串行化**。原则：**锁粒度要覆盖不变量的范围** |
| 为什么加锁顺序必须统一？ | 我不锁学生→教学班、别人锁教学班→学生，就构成循环等待 → MySQL 1213 死锁。全局统一为「学生 → 教学班」 |
| Redis 挂了还能选课吗？ | **能，且结果依然正确**。Redis 两层是性能与体验优化，正确性只依赖行锁 + 唯一约束。这是我一开始就定下的分层 |

**重复选课为什么返回 409 而不是走规则引擎失败**："本学期已选该课程"在语义上是
**资源已存在**（409），规则引擎的 `duplicate_course` 返回的是**不满足条件**（400）。
前端要能区分：前者提示"你已经选过了"，后者才展示"为什么选不了"。
所以我在锁内提前判定，特意绕开规则引擎。

**退课（`drop_course`）**：先锁教学班行，再锁选课记录（`with_for_update`），
`status=DROPPED` + `drop_at` + `drop_reason`，然后
`selected_count = max(selected_count - 1, 0)`。
**减法也必须在行锁下做**，否则会出现"退了课但名额没还回去"。
`max(..., 0)` 是防止计数被搞成负数。

### 3.3 我的课表 `Timetable.vue` → `/enrollments/timetable`

`build_timetable()` 把选课记录**装配成前端能直接渲染的网格**：

```python
grid = {f"{weekday}-{section}": [] for weekday in 1..7 for section in 1..12}
for en in enrollments:
    for slot in en.offering.time_slots:
        for section in range(slot.start_section, slot.end_section + 1):
            grid[f"{slot.weekday}-{section}"].append(cell)   # 按节次铺开
```

三个设计点：
1. **一次铺满 7×12 的格子**（含空格），前端不用自己算"这个位置有没有课"，
   直接 `v-for` 渲染表格。**把计算量放在后端一次做完，比前端每次渲染都算更划算**；
2. `color_key = course.id % 8`，前端按这个取色，同一门课颜色稳定，不用前端维护映射；
3. 同时返回 `courses` 明细列表和 `total_credits` / `course_count`，
   页面上的"本学期共 X 门课 / Y 学分"不用前端 reduce。

**这是典型的"为视图定制的服务层方法"**：`/enrollments/my` 返回原始列表，
`/enrollments/timetable` 返回装配好的网格。两个接口读同一份数据，但服务于两种消费方式。

### 3.4 我的成绩 `MyGrades.vue` → 3 个接口

| 接口 | 实现要点 |
|---|---|
| `GET /grades/my` | 复用 `list_student_grades()`；`semester_id` / `course_type` 可选筛选；**批量查学期表拼 `semester_name`** |
| `GET /grades/my/gpa` | `gpa_stat()`：累计 GPA + 已获/已修学分 + 通过/挂科门数 + 班级排名 + 逐学期趋势 |
| `GET /grades/my/failed` | 挂科清单：同一门课多次不及格**只保留最后一次**（重修提醒用） |

**`gpa_stat()` 里三个必须讲清楚的计算口径：**

| 口径 | 做法 | 为什么 |
|---|---|---|
| GPA 用**学分加权** | `Σ(绩点×学分) / Σ学分` | 3 学分专业核心课和 1 学分通识课的影响必须区分权重。算术平均下多选几门水课就能拉高 GPA，**影响保研评奖公平性** |
| 重修**只计一次** | 用 `counted: set[int]` 去重 `course_id` | 不去重就能靠反复重修刷学分和绩点 |
| 绩点**表驱动** | `GRADE_POINT_TABLE = [(90,4.0), (85,3.7), ...]` 顺序匹配第一个 `score >= threshold` | 分段规则会变，表驱动改一行数据即可，不用改逻辑 |

**班级排名的实现与一个诚实的说明**：取同班 `ENROLLED` 学生，
各自跑一次 `SUM(grade_point*credits)/SUM(credits)` 聚合，排序后取自己的位置。
**这里要主动承认**：如果面试官问"同分怎么办"，当前实现是**顺序编号**（1、2、3……），
同分不同名次。如果要"同分同名次"（竞赛排名法 / dense rank），
应该改成"排名 = 比自己分数高的人数 + 1"。我选择顺序编号是因为班内排名主要用于
评奖名额划分，顺序编号能保证名额数与人头数一一对应。

### 3.5 课程推荐 `Recommend.vue` → 2 个接口

| 接口 | 实现要点 |
|---|---|
| `GET /recommend/courses` | 四步链路 + Redis 缓存 300s |
| `GET /recommend/explain/{course_id}` | 单门课的完整打分明细 |

**四步链路：**

```
① 候选集过滤：本学期待开放 + 未修读过（best_score ∪ selected 都不算）+ remaining>0 + is_active
      ↓
② 召回（协同过滤）
   build_rating_matrix：显式反馈 = final_score/100；只选未出成绩 = 0.6 的隐式反馈
   compute_item_similarity：余弦相似度，相似度 <0.05 丢弃，每门课只留 Top20 邻居（对称写入）
   item_cf_score：Σ(相似度 × 我的评分) / Σ|相似度|      → 回答"选了 A 的人也选 B"
   user_cf_score：找 TopK=20 相似同学，看他们在这门课上的加权平均 → 回答"和你差不多的人选了 C"
      ↓
③ 规则过滤：engine.evaluate()，BLOCK 不通过的直接 continue 剔除
      ↓
④ 重排：final = cf_weight × cf_norm + (1 - cf_weight) × rule_score，排序取 TopN
```

**冷启动兜底（面试必问）**：

```python
cold_start = item_score == 0 and user_score == 0
if cold_start and offering.capacity:
    cf_norm = min(offering.selected_count / offering.capacity, 1.0) * 60   # 用课程热度做先验
```

并在理由里明确说"新开设课程，暂无历史数据，按课程热度推荐"。
**这是我在这个项目里印象最深的一次教训**：一开始按标准做法只实现 Item-CF，
用自己有成绩的账号测没问题；换新生账号演示，**推荐列表直接是空的**。
从那次以后我加了一条习惯：**新功能一定用"最差数据"的用户试一遍**——新用户、零数据、边界账号。

**规则侧打分（`rule_factor_score`）把"选了对你有没有用"量化成 0-100：**

| 因子 | 分值 | 逻辑 |
|---|---|---|
| 毕业缺口 | ≤ +35 | 该类别缺得越多分越高（**权重最高**） |
| 专业匹配 | +12 / +6 / -10 | 面向本专业 +12；面向全校 +6；不对口 -10 |
| 时间可行 | +15 / -25 | 与已选课程冲突直接 -25 |
| 年级适配 | +8 / -10 | 面向本年级 +8 |
| 课程热度 | ≤ +12 | 选课率，反映口碑，但**不能压过毕业缺口** |
| 教师信息 | 仅生成理由 | "授课教师：X（职称）" |

**可解释性（这是落地关键）**：每条推荐最多带 4 条人话理由，例如

> 修过《计算机组成原理》的同学也常选这门课；该类别（REQUIRED）仍缺 48 学分，修读优先级高

`/recommend/explain/{course_id}` 另外返回 `cf_score` / `rule_score` 的拆解。
**把算法结论翻译成人话，比提升 1% 准确率更能换来用户信任。**

**缓存策略**：key 含 `student_id + semester_id + limit + cf_weight`（参数变了就是另一份结果），
TTL 300s；**选课、退课、改规则时主动失效**。
相似度矩阵单独缓存（`cache:cf:item_sim`，TTL 600s），因为它是全量 O(n²) 计算，
代价远大于单次推荐。

### 3.6 毕业进度 `Graduation.vue` → `/analysis/graduation`

`graduation_progress()` 输出三块：

| 输出 | 实现 |
|---|---|
| 分类别完成度 | 一次查全部**通过**的成绩 join course，用 `earned_ids` 集合去重（重修只计一次），按 `CourseType` 累加到 `earned_by_type`；再遍历 `t_graduation_requirement` 算 `required / earned / gap / percent` |
| 缺口清单 | `_missing_required_courses()`：必修 + `is_active` + `major_scope` 匹配本专业（`major_scope` 为空视为全校必修）→ 排除已通过 → 再判断是"修读中"还是"未修读" → 排序（未修读优先）取前 20 |
| 状态研判 | 按下方决策树 |

**状态研判的决策树（顺序敏感）：**

```
已毕业                     → "已毕业"
学分已达标（needed <= 0）   → "学分已达标"（提示核对论文/实践环节）
已完成学期数 < 3           → "修读中"（不做外推！）
剩余学期 <= 0              → "存在延期风险"
projected < 要求 × 90%     → "需加速修读"（给出每学期建议学分）
其他                       → "预计按期毕业"
```

关键点是 `pace = earned_total / completed`，`projected = earned_total + pace × remaining`：
**用学生自己的平均修读速度外推，而不是"每学期固定 22 学分"**。
我最初就是用了固定值，结果**全体 270 人（含新生）都被判延期毕业**——
因为新生只有 0~2 个学期数据，用它外推毫无信息量。
这和风险模型里踩的坑是同一个，**同一个认知错误在两个地方各犯了一次，后来就固化成了习惯**。

### 3.7 学业体检 `MyRisk.vue` → `/analysis/my-risk`

调 `risk_service.analyze_student()`，返回五维明细 + 综合分 + 等级 + `healthy` 标志。

**五维打分模型：**

| 风险类型 | 权重 | 打分公式 |
|---|:-:|---|
| `FAILED_COURSE` 挂科 | 0.35 | `min(40 + 挂科门数×12 + 挂科学分占比×60, 100)` |
| `GPA_WARNING` 绩点 | 0.25 | `min((2.5 - GPA)/2.5 × 100 (+ 班级排名百分位×20), 100)` |
| `CREDIT_LAG` 学分落后 | 0.20 | 已获学分 < 按进度应得 × 85% 时触发 |
| `TREND_DOWN` 成绩下滑 | 0.10 | 最近两学期 GPA 环比下降 ≥ 0.3 |
| `GRADUATION_RISK` 毕业 | 0.10 | 按自身修读速度外推预计学分不足 |

综合分 = `Σ(各类型最高分 × 权重)`，等级按 `LEVEL_THRESHOLDS = [(60,HIGH), (40,MEDIUM), (0,LOW)]`。

**为什么用加权规则模型而不是机器学习**（一定会被问）：

1. **没有标注数据** —— "谁是高风险学生"没有历史标签，做不了监督学习；
2. **数据量小**（几百个学生）训不出可靠模型；
3. **可解释性刚需** —— 辅导员要拿这个结果去和学生谈话，必须能说清"凭什么判你高风险"。

演进路径我也想清楚了：等积累几年"预警—干预—结果"数据，再上逻辑回归或 GBDT，
**把当前模型作为特征**。

**两个假阳性修复（这是最能体现工程判断的地方）：**

| 坑 | 现象 | 根因 | 修复 |
|---|---|---|---|
| 学分进度基准 | 所有新生被判"落后 20 学分" | 进度基准取了**含当前学期**的学期数，可当前学期还没结束 | `completed_semesters = semester_index - 1` |
| 毕业风险外推 | **全体 270 人**被判延期毕业 | "每学期固定 22 学分"对新生零信息量 | 按学生**自身 pace** 外推 + 10% 容差 + `semester_index >= 4` 才评估 |

修复后：2026 级新生 **0/90** 命中；全体命中 144/270（HIGH 3 / MEDIUM 21 / LOW 120）。

**阈值是标定出来的，不是拍脑袋的**：常用做法定 80 分，但我实测 270 名学生的综合分
**最高才 63.3、P90 是 44.7、P75 是 35.8** —— 按 80 分阈值，"HIGH"永远是空集，
预警功能形同虚设。所以按**分位数**重新标定为 60 / 40。
真实上线后应该随数据分布定期回归标定，而不是沿用写死的常量。

---

## 四、两端功能对照表（面试官最想看到的"体系感"）

同一个业务资源，两端是两种视角 —— 这张表可以直接当答题总结：

| 业务资源 | 管理端接口 / 视角 | 学生端接口 / 视角 | 后端如何复用 |
|---|---|---|---|
| 专业、班级 | `/majors` `/classes` 增删改 + 引用检查 | 无 | 独立 |
| 学生档案 | `/students` 增删改查 + 重置密码 | 无（身份来自 token） | 独立 |
| 课程 | `/courses` + 先修课整表配置 | 无（只作为选课对象） | 独立 |
| 学期 | 增删改 + **开/关选课** | `/semesters` `/semesters/current` 只读 | 同一 service，权限与写能力不同 |
| 教学班 | `/offerings` 排课视角（容量/教师/时间地点/已选数） | `/offerings/selectable` 选课视角（可选择性/余量/冲突原因） | 同一个 `_base_out()`，学生视角**追加** `selectable` / `block_reason` |
| 选课 | `GET /enrollments` 流水查询、`/stats/by-course` 热度 | `select` / `drop` / `my` / `timetable` / `precheck` | 同一个 `t_enrollment`；写入走并发防线，读出按角色拼装 |
| 成绩 | 录入、批量录入、花名册、课程分析、班级排名 | `my` / `my/gpa` / `my/failed` | **同一套 GPA 计算**（`gpa_stat`）被学生端成绩页、毕业进度、风险模型、班级排名四处复用 |
| 规则 | `/rules` 启停调参 | 无（规则结果体现在"能不能选"） | 管理端改配置 → 学生端选课校验立刻生效 |
| 学业分析 | 扫描、预警列表、处理、学生画像、看板 | 毕业进度、个人风险体检 | **同一个 `analyze_student()`**，学生看自己、管理端批量跑同一个人 |

**这张表能被总结成一句话**：

> 「管理端改配置、看全局；学生端读结果、做决策。
> 后端不是两套接口，而是**同一套 service 上面两种权限、两种字段拼装**。
> 这也是为什么'规则配置'这个管理端功能，改完之后**学生端的选课行为立刻变了**——
> 因为两端走的是同一个规则引擎实例。」

### 顺带：管理员端和学生端的"三处差异"清单（面试可以直接背）

1. **路由不同**：`/offerings` vs `/offerings/selectable`；`/grades/offering/{id}/roster` vs `/grades/my`
2. **依赖不同**：`AdminUser`（写）/ `TeacherUser`（读）/ `CurrentStudent`（学生本人）
3. **字段不同**：同一个 `OfferingOut`，学生视角会追加 `selectable` / `block_reason` / `warnings`

---

## 五、横切能力：不管哪个功能都要吃到的四件事

这一节是"体系感"的加分项，面试官如果听够了逐个功能，会想看你能不能抽象。

### 5.1 分页的统一实现

```python
total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
rows  = db.execute(stmt.order_by(...).offset((page-1)*page_size).limit(page_size)).scalars().all()
return {"total": total, "page": page, "page_size": page_size, "items": items}
```

**`count()` over `stmt.subquery()` 而不是另写一个 count 查询**，
保证 `total` 与列表用的是**完全相同的 where 条件**。
`page_size` 在 `Query(le=200)` 里限了上限，防止前端传 100000 拖垮数据库。

### 5.2 N+1 治理的四种手段（这是我最想讲的工程能力）

| 手段 | 例子 | 效果 |
|---|---|---|
| **预加载** | `selectinload(Course.prereq_links).selectinload(...)`；`_load_offerings_stmt()` 一次加载 4 个关联 | 把 N+1 变成常数条 SQL |
| **批量 map** | `major_map` / `class_map` / `student_map` / `_prereq_name_map` / `semester_map` | 列表页从 2N+1 条降到 3~5 条 |
| **状态快照** | `build_academic_state()` | 一次选课从 N 条 SQL 降到常数级，且规则变成纯函数、可单测 |
| **聚合替代遍历** | 看板用 `group by` / `AVG()` 直接出统计 | 不在应用层循环累加 |

**并且我主动承认两处遗留的 N+1**（这种诚实反而加分）：

| 位置 | 现状 | 优化方向 |
|---|---|---|
| `gpa_stat()` 的班级排名 | 循环内对每个同学执行两条聚合 SQL（班内 30 人 = 60 条） | 改成一次 `GROUP BY student_id` 的聚合查询 |
| `_missing_required_courses()` | 循环内逐门课查 `Enrollment` 判断"修读中" | 一次把该生的选课记录查出来做内存集合判断 |

规模小的时候没问题，**但我清楚边界在哪**——这是我认为比"写了优化代码"更重要的东西。

### 5.3 Redis 的四个用途与 fail-open 降级

| 用途 | Key | 生命周期 | 挂了会怎样 |
|---|---|---|---|
| token 黑名单 | `token:blacklist:{jti}` | TTL = token 剩余有效期 | 登出后 token 保留到自然过期（**降级可接受**） |
| 选课分布式锁 | `lock:offering:{id}` | `SET NX PX` + Lua 校验持有者释放 | 跳过，**仅靠 MySQL 行锁**（**仍正确**） |
| 幂等键 | `select:idem:{sid}:{oid}:{key}` | `SET NX EX 60` | 跳过，**交给 DB 唯一约束兜底** |
| 热点缓存 | `cache:offering*` `cache:recommend*` `cache:cf:item_sim` | 写操作按前缀删 / TTL 300~600s | 直连数据库（**性能下降**） |

**所有 Redis 调用都包了 try/except 返回 None**，这是刻意的 fail-open：
**中间件故障不应该拖垮核心业务**。而之所以敢这么干，是因为正确性一开始就只押在
数据库行锁 + 唯一约束上，Redis 只承担性能职责。
这不是理论推演——我本机演示时 Redis 从来没连上过，整套功能跑得好好的。

**分布式锁释放为什么必须用 Lua**：

```lua
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end
```

场景：请求 A 拿锁 → 业务执行超过锁超时 → 锁自动释放 → 请求 B 拿到锁 →
A 执行完去释放锁，**直接 DEL 就把 B 的锁删了**。
`get` + `del` 分两步有竞态窗口，必须 Lua 原子校验持有者。

### 5.4 缓存失效与数据一致性

| 写操作 | 要失效的缓存 |
|---|---|
| 选课 / 退课 | `cache:offering*` + `cache:recommend:{student_id}*` |
| 修改规则配置 | `cache:recommend*` + `cache:offering*` |
| 录入成绩 | 不主动失效，靠 TTL（成绩变动对推荐的相似度矩阵影响是缓慢的） |

思路是**"写操作按前缀主动删，读操作按 TTL 兜底"**。
粒度粗（前缀删），但**宁可多删不可脏读**——这是缓存策略里我认为对的选择。

---

## 六、面试官可能的追问与应对

| 追问 | 回答要点 |
|---|---|
| 两端功能是不是重复写了两遍？ | 不是。只有一套 service，两端差异是**路由 + 权限依赖 + 字段拼装**三处，见第四节对照表 |
| 学生端接口怎么防越权？ | 一律不接受前端传 `student_id`，用 token 反查档案（`get_current_student`），防 IDOR |
| 管理员能删专业/班级/课程/教学班吗？ | 课程和教学班是严格拒绝的（有开课记录 / 有学生选课就不给删）。专业和班级只拦了"下面有学生"这一种引用，**班级/培养方案配置是级联删除的**——这是已知缺口，要主动说出来（见 2.1） |
| 新增学生的账号和档案怎么保证一致？ | 同一事务，`flush` 拿 id 不提前 commit，任一失败整体回滚 |
| 批量录入成绩为什么不是全成功或全失败？ | 教务场景里"部分成功 + 失败清单"比原子性更实用，老师不用重录整批 |
| 规则改了怎么立刻生效？ | 规则从 DB 读、按 priority 执行；改完清推荐/开课缓存即刻生效，**不发版** |
| 规则表被清空了会怎样？ | 回退到代码内置的 9 条规则兜底。**不放行任何校验是最危险的"配置驱动"** |
| 预警会不会每天刷屏？ | `_upsert_alert` 幂等（同生+同类型+同学期+OPEN → UPDATE），且 `_resolve_stale_alerts` 自动关闭已恢复的旧预警 |
| 风险阈值怎么定的？ | 按分位数标定（60/40），因为实测最高分只有 63.3，用常见的 80 阈值会导致 HIGH 永远为空 |
| GPA 怎么算的？ | 学分加权；重修只计一次；4.0 制表驱动分段 |
| 排名并列怎么处理？ | 当前是**顺序编号**（同分不同名次），理由是保证评奖名额与人头一一对应；如要同名次改成 dense rank |
| Redis 挂了系统还能用吗？ | 能，且结果依然正确。Redis 只承担性能职责，正确性是 DB 行锁 + 唯一约束 |
| 哪些地方还有优化空间？ | 两处已知 N+1（班级排名、毕业缺口判断）、`create_all` 应换 Alembic、风险扫描应异步化、推荐应离线预计算 |

---

## 七、一句话收尾

> 「总结一下这个问题：**管理端和学生端不是两套后端**。
> 后端有 15 张表、63 个业务接口，业务逻辑只有一份，全在 service 层；
> 管理端通过 `AdminUser` 依赖拿到写权限和排课视角，学生端通过 `CurrentStudent` 依赖
> 拿到本人视角和"能不能选、为什么不能"的决策结果。
> 两端的连接点是**规则引擎**：管理员在后台调参数，学生端的选课校验立刻按新策略执行。
> 这就是我理解的"教务管理和学生服务应该在同一套规则上运转"。」

---

### 附：可核对的事实（写代码时统计，不是估算）

| 项 | 值 | 核对方式 |
|---|---|---|
| 数据表 | **15 张** | `grep -h "__tablename__" app/models/*.py` |
| 业务接口 | **63 个** | `grep -cE "^@router\." app/api/v1/*.py` 求和 |
| 系统接口 | 2 个 | `main.py` 的 `GET /`、`GET /health` |
| 业务模块 | 10 个 + 2 个系统接口 | `api/v1/__init__.py` 的挂载顺序 |
| 规则条数 | **9 条** | `RULE_REGISTRY` |
| 数据库实测行数 | 学生 270 / 课程 41 / 教学班 77 / 选课 3281 / 成绩 3240 / 预警 317 / 专业 3 / 班级 18 / 时间段 154 / 规则 9 | `SELECT COUNT(*)` |
