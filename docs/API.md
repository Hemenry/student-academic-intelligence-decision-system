# 接口文档

- 基础地址：`http://127.0.0.1:8008/api/v1`
- 交互式文档（Swagger UI）：`http://127.0.0.1:8008/docs`
- 备用文档（ReDoc）：`http://127.0.0.1:8008/redoc`
- 接口总数：**64 个**，覆盖 10 个业务模块

## 通用约定

### 请求头
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

### 统一响应结构
```json
{
  "code": "OK",
  "message": "success",
  "data": { }
}
```

### 错误码约定

| HTTP | code | 含义 |
| :-: | --- | --- |
| 400 | `BIZ_ERROR` / `RULE_REJECTED` | 参数或业务规则不满足（如先修课未修读） |
| 401 | `AUTH_FAILED` / `TOKEN_EXPIRED` / `TOKEN_REVOKED` | 未登录 / token 过期 / token 已登出 |
| 403 | `PERMISSION_DENIED` | 角色无权访问 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `ALREADY_SELECTED` / `OFFERING_FULL` / `DUPLICATE_SUBMIT` / `LOCK_CONTENTION` | 重复选课 / 满员 / 重复提交 / 锁争用 |
| 422 | `VALIDATION_ERROR` | 请求体字段校验失败 |
| 500 | `INTERNAL_ERROR` / `DB_ERROR` | 服务端异常 |

> 前端通过 `code` 做精细化处理，不依赖 `message` 文案。

---

## 一、认证 `/auth`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/login` | 登录（管理员/教师/学生统一入口） |
| POST | `/auth/logout` | 登出，token 立即失效（Redis 黑名单） |
| GET | `/auth/me` | 当前登录用户与档案 |
| POST | `/auth/change-password` | 修改密码 |

**POST /auth/login**
```json
// 请求
{ "username": "24CS101", "password": "123456" }

// 响应
{
  "code": "OK",
  "message": "登录成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "Bearer",
    "expires_in": 7200,
    "user": { "id": 101, "username": "24CS101", "real_name": "张思远", "role": "STUDENT", "status": "ACTIVE" },
    "profile": { "id": 1, "student_no": "24CS101", "name": "张思远", "major_id": 10, "class_id": 13, "enrollment_year": 2024 }
  }
}
```

```bash
curl -X POST http://127.0.0.1:8008/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"24CS101","password":"123456"}'
```

> 安全细节：账号不存在与密码错误返回同一句提示（`BAD_CREDENTIALS`），避免被枚举出有效账号。

---

## 二、组织 `/majors` `/classes` `/teachers`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| GET | `/majors` | 教师+ | 专业列表 |
| POST | `/majors` | 管理员 | 新增专业 |
| PUT | `/majors/{major_id}` | 管理员 | 修改专业 |
| DELETE | `/majors/{major_id}` | 管理员 | 删除专业（有学生时拒绝） |
| GET | `/classes` | 教师+ | 班级列表（可按专业/年级筛选） |
| POST | `/classes` | 管理员 | 新增班级 |
| PUT | `/classes/{class_id}` | 管理员 | 修改班级 |
| DELETE | `/classes/{class_id}` | 管理员 | 删除班级（有学生时拒绝） |
| GET | `/teachers` | 教师+ | 教师列表（排课用） |

---

## 三、学生 `/students`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| GET | `/students` | 教师+ | 分页查询（keyword / major_id / class_id / grade_year / status） |
| GET | `/students/{student_id}` | 教师+ | 学生详情 |
| POST | `/students` | 管理员 | 新增学生（同事务创建登录账号） |
| PUT | `/students/{student_id}` | 管理员 | 修改档案 |
| POST | `/students/{student_id}/reset-password` | 管理员 | 重置密码，默认 123456 |
| DELETE | `/students/{student_id}` | 管理员 | 删除学生及账号 |

```bash
curl "http://127.0.0.1:8008/api/v1/students?keyword=张&page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 四、课程库 `/courses`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| GET | `/courses` | 教师+ | 分页查询（keyword / course_type） |
| GET | `/courses/{course_id}` | 教师+ | 详情（含结构化先修课） |
| POST | `/courses` | 管理员 | 新增课程 |
| PUT | `/courses/{course_id}` | 管理员 | 修改课程 |
| DELETE | `/courses/{course_id}` | 管理员 | 删除课程（有开课记录时拒绝） |
| PUT | `/courses/{course_id}/prerequisites` | 管理员 | 整表覆盖式配置先修课 |

**PUT /courses/{id}/prerequisites**
```json
[
  { "prerequisite_course_id": 12, "min_score": 60, "allow_concurrent": false },
  { "prerequisite_course_id": 15, "min_score": 70, "allow_concurrent": false }
]
```
> 采用整表覆盖而非增量更新：事务内先删后插，避免"部分更新成功"的中间态。
> 校验了自引用（先修课不能是课程自身）。

---

## 五、学期 `/semesters`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| GET | `/semesters` | 教师+ | 学期列表（含教学班数） |
| GET | `/semesters/current` | 教师+ | 当前学期 |
| POST | `/semesters` | 管理员 | 新增学期 |
| PUT | `/semesters/{semester_id}` | 管理员 | 修改学期 |
| POST | `/semesters/{semester_id}/open-selection` | 管理员 | **开启选课**（设置选课窗口 + 状态置 SELECTING） |
| POST | `/semesters/{semester_id}/close-selection` | 管理员 | 关闭选课 |

```bash
curl -X POST "http://127.0.0.1:8008/api/v1/semesters/5/open-selection?select_start_at=2026-09-01T08:00:00&select_end_at=2026-10-07T23:59:00" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

> 开启选课后，规则引擎的 `semester_window` 规则自动放行 —— 无需修改任何代码。

---

## 六、开课计划 `/offerings`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| GET | `/offerings` | 教师+ | 分页查询（semester_id / course_id / course_type / keyword / only_open） |
| POST | `/offerings` | 管理员 | 新增教学班（含排课时间段） |
| PUT | `/offerings/{offering_id}` | 管理员 | 修改（容量不能小于已选人数） |
| DELETE | `/offerings/{offering_id}` | 管理员 | 删除（已有学生选课时拒绝） |
| GET | `/offerings/selectable` | 学生 | **可选课程列表，带可选择性标注与拦截原因** |
| GET | `/offerings/{offering_id}` | 全部 | 详情（学生视角附带可选性诊断） |

**GET /offerings/selectable**（学生端核心接口）
```json
{
  "code": "OK",
  "data": [
    {
      "id": 118,
      "course_code": "CS106",
      "course_name": "软件工程",
      "credits": 3,
      "course_type": "REQUIRED",
      "teacher_name": "李娜",
      "capacity": 60,
      "selected_count": 12,
      "remaining": 48,
      "classroom": "A教学楼103",
      "time_slots": [{ "weekday": 3, "start_section": 5, "end_section": 6, "start_week": 1, "end_week": 16 }],
      "selected": false,
      "selectable": true,
      "block_reason": null,
      "warnings": ["已满足 1 门先修课要求"]
    },
    {
      "id": 126,
      "course_name": "Web应用开发",
      "selectable": false,
      "block_reason": "时间冲突：周四第1-2节(1-16周) 与《线性代数》冲突"
    }
  ]
}
```
> 列表接口就带上规则判定结果，学生不必点进去才知道被拦。
> 实现上批量装配一次状态快照后逐条跑规则，避免 N+1 查询。

---

## 七、选课 `/enrollments`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| POST | `/enrollments/select` | 学生 | **选课**（幂等键 + 分布式锁 + 行锁） |
| POST | `/enrollments/drop` | 学生 | 退课（容量回滚） |
| GET | `/enrollments/my` | 学生 | 我的选课记录（默认当前学期） |
| GET | `/enrollments/timetable` | 学生 | **个人课表**（网格 + 课程明细） |
| POST | `/enrollments/precheck` | 学生 | **选课预检**（不写库，逐条返回规则结果） |
| GET | `/enrollments` | 教师+ | 选课记录查询（多条件 + 分页） |
| GET | `/enrollments/stats/by-course` | 教师+ | 各教学班选课率排行 |

**POST /enrollments/select**
```json
// 请求
{ "offering_id": 118, "idempotent_key": "118-1757981234567-abc123" }

// 成功
{ "code": "OK", "message": "选课成功：软件工程", "data": { "id": 3100, "offering_id": 118, "status": "SELECTED", "credits": 3 } }
```

可能出现的错误：

| HTTP | code | 场景 |
| :-: | --- | --- |
| 409 | `DUPLICATE_SUBMIT` | 幂等键重复（双击提交） |
| 409 | `ALREADY_SELECTED` | 本学期已选该课程 |
| 409 | `OFFERING_FULL` | 教学班已满 |
| 409 | `LOCK_CONTENTION` | 死锁重试 3 次后仍失败 |
| 400 | `RULE_REJECTED` | 规则引擎拦截（message 里带具体原因） |

**POST /enrollments/precheck** —— 选课预检（最能体现"智能决策"）
```json
{
  "code": "OK",
  "message": "预检完成",
  "data": {
    "offering_id": 118,
    "selectable": true,
    "current_credits": 8,
    "max_credits": 30,
    "checks": [
      { "rule_key": "semester_window", "rule_name": "选课时间窗口", "passed": true, "level": "BLOCK", "message": "在选课时间内" },
      { "rule_key": "scope_match", "rule_name": "专业年级范围", "passed": true, "level": "BLOCK", "message": "符合面向范围" },
      { "rule_key": "prerequisite", "rule_name": "先修课校验", "passed": true, "level": "BLOCK", "message": "已满足 1 门先修课要求" },
      { "rule_key": "time_conflict", "rule_name": "上课时间冲突检测", "passed": true, "level": "BLOCK", "message": "无时间冲突" },
      { "rule_key": "credit_limit", "rule_name": "学期学分上限", "passed": true, "level": "BLOCK", "message": "学分校验通过：11/30" },
      { "rule_key": "already_passed", "rule_name": "已修读课程校验", "passed": true, "level": "WARN", "message": "首次修读" }
    ]
  }
}
```
> 注意 `checks` 会返回**全部 9 条规则**的结果，即使某条已拦截也不会短路 ——
> 学生一次就能看到完整诊断报告，而不是"改一次试一次"。

**GET /enrollments/timetable**
```json
{
  "code": "OK",
  "data": {
    "grid": {
      "1-1": [{ "course_name": "数据结构", "teacher_name": "张伟", "classroom": "A101", "color_key": 3 }],
      "3-5": []
    },
    "courses": [
      {
        "enrollment_id": 3100, "course_id": 20, "course_name": "数据结构",
        "course_code": "CS101", "credits": 4, "course_type": "REQUIRED",
        "teacher_name": "张伟", "classroom": "A101", "class_name": "01班",
        "time_slots": [{ "weekday": 1, "start_section": 1, "end_section": 2, "weeks_desc": "1-16周" }]
      }
    ],
    "total_credits": 18.0,
    "course_count": 5
  }
}
```
> `grid` 的 key 是 `"周几-节次"`，前端直接按二维表渲染；同一格多门课时返回数组（供冲突提示）。

---

## 八、成绩 `/grades`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| GET | `/grades/my` | 学生 | 我的成绩单（可按学期/类别筛选） |
| GET | `/grades/my/gpa` | 学生 | **GPA 与学分统计** |
| GET | `/grades/my/failed` | 学生 | 挂科清单 |
| PUT | `/grades/record` | 教师+ | 录入单条成绩 |
| PUT | `/grades/batch-record` | 教师+ | 批量录入（单条失败不影响其他） |
| GET | `/grades/offering/{offering_id}/roster` | 教师+ | 教学班花名册（含成绩） |
| GET | `/grades/stats/course/{course_id}` | 教师+ | 课程成绩分析（均分/及格率/分布） |
| GET | `/grades/stats/class-rank` | 教师+ | 班级成绩排名 |

**GET /grades/my/gpa**
```json
{
  "code": "OK",
  "data": {
    "overall_gpa": 3.647,
    "total_credits_earned": 62.0,
    "total_credits_attempted": 68.0,
    "passed_course_count": 20,
    "failed_course_count": 2,
    "rank_in_class": 2,
    "class_size": 15,
    "by_semester": [
      { "semester_id": 1, "semester_name": "2024-2025学年第一学期", "credits": 19.0, "gpa": 3.72, "course_count": 6, "passed": 6 }
    ]
  }
}
```

**PUT /grades/batch-record**
```json
{
  "items": [
    { "enrollment_id": 3100, "usual_score": 88, "exam_score": 92, "final_score": null, "usual_weight": 0.4 }
  ]
}
// final_score 传 null 时按 usual_weight 加权自动计算
```
> 批量接口逐条处理，单条失败不回滚整批，最后返回 `{ success: 12, failed: [{enrollment_id, error}] }`。
> 教务场景老师一次录几十条，不能因为一条异常就整批重来。

---

## 九、智能推荐 `/recommend`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| GET | `/recommend/courses` | 学生 | 个性化推荐（可调 CF 权重） |
| GET | `/recommend/explain/{course_id}` | 学生 | 推荐依据说明 |

**GET /recommend/courses?limit=5&cf_weight=0.55**
```json
{
  "code": "OK",
  "data": [
    {
      "offering_id": 118,
      "course_id": 20,
      "course_code": "CS106",
      "course_name": "软件工程",
      "credits": 3,
      "course_type": "REQUIRED",
      "teacher_name": "李娜",
      "score": 52.77,
      "cf_score": 54.28,
      "rule_score": 50.93,
      "remaining": 48,
      "reason": [
        "修过《计算机组成原理》的同学也常选这门课",
        "该类别（REQUIRED）仍缺 48 学分，修读优先级高",
        "授课教师：李娜（副教授）"
      ]
    }
  ]
}
```
> `cf_weight=0` 为纯规则推荐，`cf_weight=1` 为纯协同过滤，可现场对比冷启动差异。

---

## 十、学业分析 `/analysis` 与规则 `/rules`

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | :-: | --- |
| GET | `/analysis/graduation` | 学生 | **毕业进度分析** |
| GET | `/analysis/my-risk` | 学生 | **个人学业体检** |
| POST | `/analysis/risk-scan` | 管理员 | **批量风险扫描**（可按班级/专业） |
| GET | `/analysis/alerts` | 教师+ | 预警列表（按类型/等级/状态筛选） |
| POST | `/analysis/alerts/{alert_id}/handle` | 教师+ | 处理/忽略预警 |
| GET | `/analysis/student/{student_id}/report` | 教师+ | 学生学业报告（画像） |
| GET | `/analysis/dashboard` | 教师+ | 教务数据看板 |
| GET | `/rules` | 教师+ | 选课规则列表 |
| PUT | `/rules/{rule_id}` | 管理员 | 启停/调参规则 |

**GET /analysis/graduation**
```json
{
  "code": "OK",
  "data": {
    "major_name": "计算机科学与技术",
    "required_total": 160.0,
    "earned_total": 62.0,
    "progress_percent": 38.8,
    "by_type": [
      { "course_type": "REQUIRED", "label": "专业必修", "required_credits": 72.0, "earned_credits": 3.0, "gap": 69.0, "percent": 4.2 },
      { "course_type": "PUBLIC", "label": "公共必修", "required_credits": 48.0, "earned_credits": 41.0, "gap": 7.0, "percent": 85.4 }
    ],
    "missing_required_courses": [
      { "course_id": 31, "course_code": "CS106", "course_name": "软件工程", "credits": 3.0, "status": "未修读" }
    ],
    "estimated_status": "需加速修读",
    "suggestion": "尚缺 98 学分，剩余 4 个学期按每学期 22 学分估算仅能完成 88 学分，建议提高选课强度。",
    "gpa": 3.647,
    "semester_index": 5
  }
}
```

**GET /analysis/my-risk**
```json
{
  "code": "OK",
  "data": {
    "risk_score": 41.9,
    "risk_level": "LOW",
    "findings": [
      {
        "risk_type": "FAILED_COURSE",
        "risk_level": "MEDIUM",
        "risk_score": 70.5,
        "title": "存在 2 门课程不及格",
        "reasons": [
          "累计挂科 2 门，合计 6 学分（占已修学分 9%）",
          "未通过课程：数据库系统原理(52分)、编译原理(47分)"
        ],
        "suggestion": "建议本学期优先安排重修，并联系任课教师做针对性补强。"
      }
    ],
    "healthy": false
  }
}
```

**POST /analysis/risk-scan?class_id=13&persist=true**
```json
{
  "code": "OK",
  "message": "扫描完成，共 15 名学生存在风险，其中高风险 3 人",
  "data": {
    "scanned": 15,
    "high_risk": 3,
    "items": [
      {
        "student_id": 5, "student_no": "24CS102", "student_name": "李梓涵",
        "risk_score": 68.2, "risk_level": "MEDIUM",
        "findings": [ { "risk_type": "GPA_WARNING", "risk_level": "MEDIUM", "title": "累计绩点偏低（1.92）" } ]
      }
    ]
  }
}
```

**PUT /rules/{rule_id}** —— 改规则不改代码
```json
// 请求：把学期学分上限从 30 调到 32
{ "enabled": true, "params": { "max_credits": 32, "warn_gpa": 1.5, "tighten_credits": 6 } }
```
> 保存后自动清理 `cache:recommend*` 与 `cache:offering*`，即刻生效。

---

## 十一、系统接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 服务信息（含 Redis 可用性） |
| GET | `/health` | 健康检查（DB / Redis 连通性） |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc |
| GET | `/openapi.json` | OpenAPI 3.1 规范 |

---

## 十二、端到端验证

```bash
# 启动服务后执行，覆盖认证、越权、选课、幂等、课表、成绩、推荐、风险、看板、登出
python backend/scripts/api_smoke_test.py
# 预期：通过 34 项，失败 0 项

# 并发抢课压测（验证行锁防超卖）
python backend/scripts/concurrency_test.py --threads 40
# 预期：容量 3 的教学班恰好 3 人成功，计数器与真实记录数一致
```
