<template>
  <div>
    <!-- ============ 学生首页 ============ -->
    <template v-if="userStore.isStudent">
      <h2 class="page-title">学业概览</h2>
      <p class="page-desc">
        系统已同步你的成绩、选课与培养方案数据。以下指标由「成绩统计 + 规则引擎 + 风险模型」实时计算得出。
      </p>

      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-label">累计 GPA</div>
          <div class="stat-value brand">{{ gpa.overall_gpa ?? '—' }}</div>
          <div class="stat-hint">
            班级排名 {{ gpa.rank_in_class ?? '—' }} / {{ gpa.class_size ?? '—' }}
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-label">已获学分</div>
          <div class="stat-value">{{ gpa.total_credits_earned ?? '—' }}</div>
          <div class="stat-hint">培养方案要求 {{ grad.required_total ?? '—' }} 学分</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">本学期已选学分</div>
          <div class="stat-value">{{ tt.total_credits ?? 0 }}</div>
          <div class="stat-hint">{{ tt.course_count ?? 0 }} 门课程 / 上限 30 学分</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">学业风险等级</div>
          <div class="stat-value" :class="riskClass">{{ riskLabel }}</div>
          <div class="stat-hint">风险分 {{ risk.risk_score ?? 0 }} ／ 命中 {{ risk.findings?.length || 0 }} 项</div>
        </div>
      </div>

      <div class="two-col">
        <div class="card">
          <h3 class="sec-title">毕业进度</h3>
          <el-progress :percentage="grad.progress_percent || 0" :stroke-width="14" status="success" />
          <div class="muted" style="margin-top: 8px">
            已获 {{ grad.earned_total || 0 }} / {{ grad.required_total || 0 }} 学分 ·
            {{ grad.estimated_status || '—' }}
          </div>
          <p class="suggest">{{ grad.suggestion }}</p>
        </div>

        <div class="card">
          <h3 class="sec-title">为你推荐（协同过滤 + 规则引擎）</h3>
          <div v-if="recommend.length === 0" class="muted">暂无推荐，去「智能选课」看看可选课程吧</div>
          <div v-for="item in recommend" :key="item.offering_id" class="rec-row">
            <div>
              <b>{{ item.course_name }}</b>
              <span class="muted"> · {{ item.credits }} 学分 · {{ item.teacher_name || '教师待定' }}</span>
              <div class="muted">{{ item.reason?.[0] }}</div>
            </div>
            <el-tag type="primary" effect="plain">{{ item.score }} 分</el-tag>
          </div>
          <el-button text type="primary" @click="router.push('/recommend')">查看全部推荐 →</el-button>
        </div>
      </div>

      <div class="card">
        <h3 class="sec-title">本学期课表速览</h3>
        <el-table :data="tt.courses || []" size="small" stripe>
          <el-table-column prop="course_code" label="课程代码" width="110" />
          <el-table-column prop="course_name" label="课程名称" min-width="160" />
          <el-table-column prop="credits" label="学分" width="70" />
          <el-table-column prop="teacher_name" label="教师" width="100" />
          <el-table-column label="上课时间" min-width="220">
            <template #default="{ row }">
              <span v-if="!row.time_slots?.length" class="muted">待排</span>
              <span v-else>{{ row.time_slots.map(slotText).join('；') }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="classroom" label="教室" width="130" />
        </el-table>
      </div>
    </template>

    <!-- ============ 管理/教师首页 ============ -->
    <template v-else>
      <h2 class="page-title">教务数据看板</h2>
      <p class="page-desc">教务运行总览：学生规模、课程资源、选课情况与学业风险分布。</p>

      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-label">在校学生</div>
          <div class="stat-value brand">{{ counters.student_count ?? '—' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">课程总数</div>
          <div class="stat-value">{{ counters.course_count ?? '—' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">教学班（含历史）</div>
          <div class="stat-value">{{ counters.offering_count ?? '—' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">选课记录</div>
          <div class="stat-value">{{ counters.enrollment_count ?? '—' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">已出成绩 / 平均分</div>
          <div class="stat-value">{{ counters.graded_count ?? '—' }}</div>
          <div class="stat-hint">全校平均分 {{ counters.average_score ?? '—' }}</div>
        </div>
      </div>

      <div class="two-col">
        <div class="card">
          <h3 class="sec-title">学业预警分布</h3>
          <div class="risk-bars">
            <div class="risk-bar" v-for="row in riskBars" :key="row.label">
              <span class="risk-name">{{ row.label }}</span>
              <div class="risk-track">
                <div class="risk-fill" :style="{ width: row.percent + '%', background: row.color }"></div>
              </div>
              <span class="risk-num">{{ row.value }} 条</span>
            </div>
          </div>
          <div class="muted" style="margin-top: 10px">未处理预警合计 {{ risk.total_open || 0 }} 条</div>
        </div>

        <div class="card">
          <h3 class="sec-title">快捷操作</h3>
          <div class="quick-actions">
            <el-button type="primary" @click="router.push('/offerings')">开课计划</el-button>
            <el-button @click="router.push('/grade-entry')">成绩录入</el-button>
            <el-button @click="router.push('/alerts')">学业预警</el-button>
            <el-button @click="router.push('/enroll-stats')">选课统计</el-button>
            <el-button @click="router.push('/students')">学生管理</el-button>
            <el-button @click="router.push('/rules')">选课规则</el-button>
          </div>
          <p class="muted" style="margin-top: 12px; line-height: 1.9">
            提示：学业预警由「挂科门数、GPA、学分进度、成绩趋势、毕业风险」五个维度加权计算，
            可在「学业预警」页一键扫描并指派辅导员跟进。
          </p>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { analysisApi, enrollmentApi, gradeApi, recommendApi } from '@/api'

const router = useRouter()
const userStore = useUserStore()

const gpa = ref<Record<string, any>>({})
const grad = ref<Record<string, any>>({})
const tt = ref<Record<string, any>>({})
const risk = ref<Record<string, any>>({})
const recommend = ref<any[]>([])

const counters = ref<Record<string, any>>({})
const riskOverview = ref<Record<string, any>>({ by_level: {}, by_type: {}, total_open: 0 })

const riskLabel = computed(() => {
  const map: Record<string, string> = { HIGH: '高风险', MEDIUM: '中风险', LOW: '低风险' }
  if (!risk.value.findings?.length) return '正常'
  return map[risk.value.risk_level] || '正常'
})
const riskClass = computed(() => {
  if (!risk.value.findings?.length) return 'success'
  return risk.value.risk_level === 'HIGH' ? 'danger' : ''
})

const riskBars = computed(() => {
  const levels = riskOverview.value.by_level || {}
  const total = Math.max(riskOverview.value.total_open || 1, 1)
  return [
    { label: '高风险', value: levels.HIGH || 0, color: '#e5484d', percent: ((levels.HIGH || 0) / total) * 100 },
    { label: '中风险', value: levels.MEDIUM || 0, color: '#f59e0b', percent: ((levels.MEDIUM || 0) / total) * 100 },
    { label: '低风险', value: levels.LOW || 0, color: '#12a150', percent: ((levels.LOW || 0) / total) * 100 },
  ]
})

function slotText(s: any) {
  const w = '一二三四五六日'[s.weekday - 1]
  return `周${w} 第${s.start_section}-${s.end_section}节`
}

onMounted(async () => {
  if (userStore.isStudent) {
    const [g, gr, t, r, rec] = await Promise.allSettled([
      gradeApi.myGpa(),
      analysisApi.graduation(),
      enrollmentApi.timetable(),
      analysisApi.myRisk(),
      recommendApi.courses({ limit: 3 }),
    ])
    if (g.status === 'fulfilled') gpa.value = g.value as any
    if (gr.status === 'fulfilled') grad.value = gr.value as any
    if (t.status === 'fulfilled') tt.value = t.value as any
    if (r.status === 'fulfilled') risk.value = r.value as any
    if (rec.status === 'fulfilled') recommend.value = rec.value as any
  } else {
    const d: any = await analysisApi.dashboard()
    counters.value = d.counters || {}
    riskOverview.value = d.risk_overview || { by_level: {}, by_type: {}, total_open: 0 }
  }
})
</script>

<style scoped>
.sec-title {
  font-size: 14px;
  margin: 0 0 12px;
  color: #2c3a52;
}

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
}

@media (max-width: 1100px) {
  .two-col {
    grid-template-columns: 1fr;
  }
}

.rec-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px dashed #eef1f6;
}

.suggest {
  font-size: 13px;
  color: #50607a;
  line-height: 1.8;
  margin: 10px 0 0;
}

.risk-bars {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.risk-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.risk-name {
  width: 60px;
  color: #56657d;
}

.risk-track {
  flex: 1;
  height: 12px;
  background: #f1f4f9;
  border-radius: 6px;
  overflow: hidden;
}

.risk-fill {
  height: 100%;
  border-radius: 6px;
  transition: width 0.4s;
}

.risk-num {
  width: 60px;
  text-align: right;
  color: #7b8798;
}

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
</style>
