# 架构与核心设计

## 一、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│  浏览器（Vue3 + Vite + Element Plus）                          │
│  ├─ Pinia 维护 token / 用户 / 角色                             │
│  ├─ 路由守卫按 meta.roles 拦截越权跳转                          │
│  └─ axios 拦截器：自动带 JWT + 统一解包 {code,message,data}      │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP / JSON（开发环境走 Vite 代理）
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI 应用层（app/api/v1，10 个模块 / 64 个接口）             │
│  ├─ 依赖注入鉴权：get_current_user / require_admin / ...        │
│  ├─ 请求校验：Pydantic Schema                                   │
│  └─ 全局异常处理：BizError / 校验错误 / DB 错误 → 统一结构        │
├──────────────────────────────────────────────────────────────┤
│  服务层（app/services）—— 业务核心，与 HTTP 解耦                 │
│  ├─ rule_engine      选课规则引擎（9 条规则 + 可配置）           │
│  ├─ selection_service 选课/退课（三重并发防线）                  │
│  ├─ recommend_service 协同过滤 + 规则因子混合推荐                │
│  ├─ risk_service      五维学业风险识别                          │
│  ├─ grade_service     成绩、GPA、排名统计                       │
│  └─ graduation_service 毕业进度分析                             │
├──────────────────────────────────────────────────────────────┤
│  数据层                                                        │
│  ├─ SQLAlchemy 2.0（Mapped 声明式 + QueuePool + selectinload）  │
│  ├─ MySQL 8.0（InnoDB，16 张表，唯一约束 + 行锁）                 │
│  └─ Redis（token 黑名单、分布式锁、热点缓存、推荐缓存）            │
└──────────────────────────────────────────────────────────────┘
```

**分层原则**：接口层只做参数校验与响应拼装，业务规则全部沉在 service 层。
好处是同一套选课逻辑可以被 HTTP 接口、脚本、定时任务复用，不受传输层约束。

## 二、鉴权与权限设计

### 认证流程
1. `POST /auth/login` 校验 bcrypt 密码 → 签发 JWT（payload 含 `sub`/`role`/`jti`/`exp`）；
2. 前端把 token 存 localStorage，axios 拦截器统一加 `Authorization: Bearer <token>`；
3. 后端 `get_current_user` 依赖解析 token → 校验黑名单 → 查库确认账号状态。

### 为什么要 jti + Redis 黑名单
JWT 是无状态的，签出去就无法撤回，导致「登出后 token 仍然有效」。
引入 `jti`（token 唯一 ID）后，登出时把 `jti` 写入 Redis 并设置与 token 相同的 TTL，
鉴权时先查黑名单即可实现**即时失效**，TTL 到期自动清理，不会无限堆积。

### 数据权限（防越权）
学生类接口（我的课表、我的成绩、我的风险）**不接受前端传 student_id**，
一律从 token 反查当前登录学生的档案：

```python
def get_current_student(db, user) -> Student:
    if user.role != UserRole.STUDENT:
        raise PermissionError_("该接口仅供学生使用")
    return db.scalar(select(Student).where(Student.user_id == user.id))
```

这样从根上杜绝了「改个 id 就能看别人成绩」的 IDOR 漏洞 —— 权限校验依赖服务端身份，而不是客户端参数。

### 角色矩阵

| 能力 | 学生 | 教师 | 管理员 |
| --- | :-: | :-: | :-: |
| 选课 / 退课 / 课表 / 成绩查询 | ✓ | | |
| 推荐 / 毕业进度 / 学业体检 | ✓ | | |
| 成绩录入 | | ✓ | ✓ |
| 教学班花名册、预警查看与处理 | | ✓ | ✓ |
| 专业 / 班级 / 课程 / 学期 / 开课计划 | | | ✓ |
| 学生管理、规则配置 | | | ✓ |

## 三、选课并发控制（核心难点）

### 要同时保证的三件事
1. **不超卖**：容量 60 的教学班，绝不能选进第 61 人；
2. **不重复**：同一学生同一门课本学期只有一条有效记录；
3. **不冲突**：时间不打架、先修课满足、学分不超上限。

### 三重防线

```
请求 → ① Redis 幂等键(SET NX EX 60)
          ↓ 未命中重复
       ② Redis 分布式锁(SET NX PX + Lua 释放持有者校验)
          ↓ 拿到锁
       ③ MySQL 事务：
          SELECT * FROM t_student WHERE id=? FOR UPDATE      ← 锁学生行
          SELECT * FROM t_course_offering WHERE id=? FOR UPDATE ← 锁教学班行
          规则引擎全量校验
          UPDATE selected_count = selected_count + 1
          INSERT t_enrollment
          COMMIT
          ↓ 唯一约束兜底 UNIQUE(student_id, course_id, semester_id)
```

**为什么必须先锁学生行**：两个请求同时选「时间冲突的两门课」，各自只锁教学班行时都能通过冲突校验。
锁住学生行后，同一学生的选课被串行化，第二个请求会看到第一个已提交的选课记录，冲突检测才准确。

**为什么加锁顺序必须全局统一**（学生 → 教学班）：若两个事务反向加锁，就会互相等待对方持有的锁，
形成死锁（MySQL 报 1213 Error）。统一顺序是最省事也最有效的死锁预防手段。

**为什么必须用 `SELECT ... FOR UPDATE` 而不是普通 SELECT**：
MySQL 默认隔离级别 REPEATABLE READ 下，普通 `SELECT` 读的是事务开始时的快照，
拿到的可能是过期计数，`count++` 会基于脏快照算错。`FOR UPDATE` 才是"读最新已提交 + 加排他锁"。

**兜底与自愈**：
- 即使前三层都出现意外，数据库唯一约束会抛 IntegrityError → 返回 409，数据不会脏；
- 捕获 1213（死锁）/1205（锁等待超时）自动重试最多 3 次，生产环境"能自愈"比"永不出错"更现实；
- Redis 不可用时锁自动降级，仅靠 MySQL 行锁保证正确性（性能下降但结果依然正确）。

### 实测结果

```
$ python scripts/concurrency_test.py --threads 40
目标教学班：《艺术鉴赏》 容量 3，并发线程 40
抢课成功          ：3 人
因满员被拒        ：33 人
因其他原因被拒    ：4 人  （时间冲突，属规则正确拦截）
教学班计数器      ：3
数据库真实记录数  ：3
结论：未超卖 ✅
```

## 四、规则引擎

### 设计模式：责任链 + 策略模式 + 注册表

```python
class BaseRule:
    rule_key: str
    name: str
    default_priority: int
    default_params: dict

    def check(self, ctx: RuleContext) -> RuleResult: ...   # 纯函数，无副作用

RULE_REGISTRY = {r.rule_key: r for r in [SemesterWindowRule(), OfferingOpenRule(), ...]}
```

- **配置驱动**：规则元数据存在 `t_select_rule` 表，`RuleEngine.from_db()` 读取启用的规则并按 priority 排序；
- **策略模式**：每条规则一个类，新增规则只需实现 `check()` 并注册，符合开闭原则；
- **纯函数化**：规则只读 `RuleContext`，不查库不写库，因此可以脱离数据库做单元测试。

### 9 条规则

| 规则 | 级别 | 说明 |
| --- | --- | --- |
| `semester_window` | BLOCK | 选课时间窗口 + 学期状态 + 教学班归属学期 |
| `offering_open` | BLOCK | 教学班是否开放、学籍是否在读 |
| `scope_match` | BLOCK | 面向专业 / 年级范围 |
| `duplicate_course` | BLOCK | 本学期是否已选该课程 |
| `already_passed` | WARN | 已修读并及格 → 提示走重修通道；曾不及格 → 提示保留两次记录 |
| `prerequisite` | BLOCK | 先修课是否修读且达到最低分数 |
| `time_conflict` | BLOCK | 同一天 + 节次区间重叠 + 周次区间重叠 → 冲突 |
| `credit_limit` | BLOCK | 学期学分上限；**GPA 低于阈值时动态收紧上限** |
| `graduation_gap` | WARN | 临近毕业仍选通识选修 → 提示优先补专业必修 |

### 关键设计决策

**为什么不做短路？**
如果第一条规则拦住就立即返回，学生只能"改一次试一次"。
把 9 条规则全部跑完，前端一次性展示完整诊断报告 —— 用户一次就看清所有问题，
排查体验和客服成本都显著下降。这在 `POST /enrollments/precheck` 里体现得最明显。

**为什么分 BLOCK / WARN 两级？**
教务场景里很多判断不是"能不能"，而是"值不值"。比如「已修读过并及格」不能一刀切禁止，
但要提示学生重修需要走专门通道。两级判定让规则既能守住底线，又不牺牲灵活性。

**为什么 `credit_limit` 里塞了业务决策？**
系统把"学业预警学生限制选课学分"落成了规则参数（`warn_gpa` / `tighten_credits`）。
这不是单纯的校验，而是把教务管理决策算法化 —— 累计绩点低于 1.5 的学生，学分上限自动下调 6 分。

### 性能优化：学业状态快照
选课校验要读本学期已选课程、时间占用、历史成绩、GPA 等数据。
如果每条规则各自查库，一次选课就是 N 条 SQL（典型 N+1）。
`build_academic_state()` 一次装配成内存快照，规则只读快照：

```python
@dataclass
class AcademicState:
    student: Student
    semester: Semester | None
    enrollments: list[Enrollment]
    time_blocks: list[TimeBlock]          # 已占用的时间块
    best_score: dict[int, float]          # course_id → 最好成绩
    passed_course_ids: set[int]
    current_credits: float
    overall_gpa: float
    earned_credits: float
```

## 五、智能推荐

### 混合策略

```
① 候选集：当前学期开放、有余量、未修读过、课程有效
       ↓
② 召回：Item-CF + User-CF 加权
   - 评分矩阵：{course_id: {student_id: rating}}
     显式反馈 = final_score/100；只选未出成绩 = 0.6 隐式反馈
   - Item-CF：课程间余弦相似度（Top20 邻居存 Redis），预测"选了 A 的人常选 B"
   - User-CF：学生间余弦相似度取 TopK 邻居，预测"和你相近的同学选了 C"
   - cf_score = item_score × 0.6 + user_score × 0.4
       ↓
③ 过滤：规则引擎 BLOCK 级不通过的直接剔除（保证推荐出来的课一定选得上）
       ↓
④ 重排：final = cf_weight × cf_norm + (1 - cf_weight) × rule_score
   rule_score 因子：毕业缺口(35) 专业匹配(12) 时间可行(15) 年级适配(8) 课程热度(12)
```

### 冷启动兜底
新生没有任何历史成绩，协同过滤算不出相似度。此时检测 `item_score == user_score == 0`，
改用课程热度（选课率）作为先验分，并在推荐理由里明确标注"新开设课程，暂无历史数据"。
实测 2026 级新生能正常拿到 5 条推荐。

### 可解释性
每条推荐都生成人能读懂的推荐理由，例如：

> 修过《计算机组成原理》的同学也常选这门课；该类别（REQUIRED）仍缺 48 学分，修读优先级高

并提供 `GET /recommend/explain/{course_id}` 查询完整打分明细（CF 分 / 规则分 / 理由列表）。
推荐系统落地的最大阻力是"黑箱"，把算法结论翻译成人话比提升 1% 准确率更重要。

### 性能
- 相似度矩阵 O(n²)，课程量级（千门）内可接受；矩阵缓存 Redis，TTL 10 分钟；
- 推荐结果按 `student_id + 参数` 缓存 5 分钟，选课/退课/录成绩时主动失效；
- 真实生产应改为离线任务（Spark/定时）预计算矩阵写回 Redis，在线只做查表 + 排序。

## 六、学业风险识别

五类风险各自算分（0-100），加权合成综合风险分：

| 风险类型 | 权重 | 判定逻辑 |
| --- | :-: | --- |
| FAILED_COURSE 挂科 | 0.35 | 40 + 挂科门数×12 + 挂科学分占比×60 |
| GPA_WARNING 绩点 | 0.25 | (2.5 - GPA)/2.5×100 + 班级排名百分位×20 |
| CREDIT_LAG 学分落后 | 0.20 | 实际学分低于按学期进度应得学分的 85% 时触发 |
| TREND_DOWN 成绩下滑 | 0.10 | 最近两学期 GPA 环比下降 ≥ 0.3 |
| GRADUATION_RISK 毕业 | 0.10 | 缺口学分 > 剩余学期×22 学分 |

综合分 → 等级映射：**≥60 高风险，≥40 中风险，其余低风险**。

阈值不是拍脑袋定的，而是按风险分的分位数标定：实测 270 名学生的综合风险分最高 63.3、
P90 为 44.7、P75 为 35.8，取 60 对应约 Top 1%、40 对应约 Top 17%。
如果沿用常见的固定 80 分阈值，在本数据规模下"高风险"永远是空集，预警功能形同虚设。
真实上线后应随数据分布定期回归标定，而不是沿用一次性写死的常量。

两条工程细节：
- **可解释**：每条预警携带 `reason`（JSON 数组，说明各项扣分来源）和 `suggestion`（干预建议）。
  辅导员最需要知道"为什么被判高风险"，而不是一个孤零零的分数；
- **幂等落库**：同一学生 + 同类型 + 同学期 + 未处理状态时做 update 而非 insert，避免反复扫描刷屏。

## 七、Redis 的四个用途与降级策略

| 用途 | Key 设计 | 失效策略 |
| --- | --- | --- |
| token 黑名单 | `token:blacklist:{jti}` | TTL = token 剩余有效期 |
| 选课分布式锁 | `lock:offering:{id}` | SET NX PX + Lua 校验持有者后删除 |
| 热点缓存 | `cache:offering*` / `cache:recommend*` | 选课、退课、改规则时主动删前缀 |
| 相似度矩阵 | `cache:cf:item_sim` | TTL 600s |

**降级设计（fail-open）**：所有 Redis 调用都包了 try/except。
Redis 不可用时：缓存读写返回 None（直连数据库）、锁自动跳过（仅靠 MySQL 行锁）、
黑名单校验返回 False（登出后 token 保留至自然过期）。
结果是**性能下降但业务不中断** —— 中间件故障不应该拖垮核心业务。

## 八、可扩展性与演进方向

| 现状 | 生产级演进 |
| --- | --- |
| `create_all` 建表 | 改用 Alembic 版本化迁移 + 灰度 DDL |
| 同步风险扫描 | 迁移到 Celery/APScheduler 异步任务 + 进度查询 |
| 在线计算相似度矩阵 | 离线预计算（Spark）写回 Redis，在线只查表 |
| 单库单表 | 选课记录按学期分表 + 读写分离（主库写、从库统计） |
| 手动重试死锁 | 引入消息队列削峰，选课请求异步化 + 结果轮询 |
| 单体部署 | 拆分为认证/教务/分析服务，网关统一鉴权 |
