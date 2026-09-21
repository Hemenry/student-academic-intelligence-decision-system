<template>
  <div>
    <h2 class="page-title">我的成绩</h2>
    <p class="page-desc">
      GPA 采用<strong>学分加权</strong>计算（3 学分专业课的影响大于 1 学分通识课）；
      重修课程只取通过的那一次计入，避免重复刷绩点。
    </p>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">累计 GPA</div>
        <div class="stat-value brand">{{ stat.overall_gpa ?? '—' }}</div>
        <div class="stat-hint">4.0 分制 · 学分加权</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">已获学分</div>
        <div class="stat-value">{{ stat.total_credits_earned ?? '—' }}</div>
        <div class="stat-hint">累计修读 {{ stat.total_credits_attempted ?? '—' }} 学分</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">通过 / 挂科</div>
        <div class="stat-value">
          {{ stat.passed_course_count ?? 0 }}
          <span style="font-size: 15px; color: #e5484d"> / {{ stat.failed_course_count ?? 0 }}</span>
        </div>
        <div class="stat-hint">门次统计</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">班级排名</div>
        <div class="stat-value">
          {{ stat.rank_in_class ?? '—' }}
          <span style="font-size: 15px; color: #7b8798">/ {{ stat.class_size ?? '—' }}</span>
        </div>
        <div class="stat-hint">按累计 GPA 排序</div>
      </div>
    </div>

    <div class="card">
      <h3 class="sec-title">各学期 GPA 趋势</h3>
      <div class="chart">
        <div v-for="s in stat.by_semester || []" :key="s.semester_id" class="chart-col">
          <div class="chart-value">{{ s.gpa }}</div>
          <div class="chart-bar-wrap">
            <div class="chart-bar" :style="{ height: barHeight(s.gpa) }"></div>
          </div>
          <div class="chart-label">{{ shortName(s.semester_name) }}</div>
        </div>
        <div v-if="!(stat.by_semester || []).length" class="muted">暂无成绩数据</div>
      </div>
    </div>

    <div class="card">
      <div class="toolbar">
        <el-select v-model="filters.semester_id" placeholder="全部学期" clearable style="width: 200px" @change="load">
          <el-option v-for="s in semesters" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-select v-model="filters.course_type" placeholder="全部类别" clearable style="width: 150px" @change="load">
          <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <div style="flex: 1"></div>
        <el-tag v-if="failed.length" type="danger" effect="plain">挂科 {{ failed.length }} 门，请及时重修</el-tag>
      </div>

      <el-table :data="grades" v-loading="loading" size="small" border stripe>
        <el-table-column prop="course_code" label="代码" width="110" />
        <el-table-column prop="course_name" label="课程名称" min-width="160" />
        <el-table-column label="类别" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.course_type)">{{ typeLabel(row.course_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="credits" label="学分" width="70" />
        <el-table-column prop="usual_score" label="平时" width="70" />
        <el-table-column prop="exam_score" label="期末" width="70" />
        <el-table-column prop="final_score" label="总评" width="80">
          <template #default="{ row }">
            <b :class="row.is_pass ? 'pass' : 'fail'">{{ row.final_score }}</b>
          </template>
        </el-table-column>
        <el-table-column prop="grade_point" label="绩点" width="70" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_pass ? 'success' : 'danger'">{{ row.is_pass ? '通过' : '不及格' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="semester_name" label="学期" width="180" />
        <el-table-column label="重修" width="70">
          <template #default="{ row }">
            <span v-if="row.is_retake" class="muted">第 {{ row.attempt_no }} 次</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="failed.length" class="card">
      <h3 class="sec-title">挂科清单（重修提醒）</h3>
      <el-table :data="failed" size="small" border>
        <el-table-column prop="course_code" label="代码" width="110" />
        <el-table-column prop="course_name" label="课程名称" min-width="160" />
        <el-table-column prop="credits" label="学分" width="80" />
        <el-table-column prop="final_score" label="成绩" width="80" />
        <el-table-column label="建议" min-width="200">
          <template #default>该课程学分会计入毕业缺口，建议在下一学期优先重修。</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { gradeApi, semesterApi } from '@/api'

const stat = ref<Record<string, any>>({})
const grades = ref<any[]>([])
const failed = ref<any[]>([])
const semesters = ref<any[]>([])
const loading = ref(false)
const filters = reactive<{ semester_id?: number; course_type?: string }>({ semester_id: undefined, course_type: undefined })

const typeOptions = [
  { label: '专业必修', value: 'REQUIRED' },
  { label: '专业选修', value: 'ELECTIVE' },
  { label: '公共必修', value: 'PUBLIC' },
  { label: '通识选修', value: 'GENERAL' },
]
const typeLabel = (t: string) => typeOptions.find((o) => o.value === t)?.label || t
const typeTag = (t: string) => ({ REQUIRED: 'danger', ELECTIVE: 'warning', PUBLIC: 'primary', GENERAL: 'success' } as any)[t] || 'info'
const shortName = (name: string) => (name || '').replace('学年', '').replace('学期', '')

function barHeight(gpa: number) {
  return `${Math.max((gpa / 4.0) * 100, 3)}%`
}

async function load() {
  loading.value = true
  try {
    grades.value = (await gradeApi.my({ ...filters })) as any
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  const [s, g, f] = await Promise.all([gradeApi.myGpa(), gradeApi.my(), gradeApi.myFailed()])
  stat.value = s as any
  grades.value = g as any
  failed.value = f as any
  semesters.value = (await semesterApi.list()) as any
})
</script>

<style scoped>
.sec-title {
  font-size: 14px;
  margin: 0 0 12px;
  color: #2c3a52;
}

.chart {
  display: flex;
  align-items: flex-end;
  gap: 26px;
  height: 190px;
  padding: 0 6px;
}

.chart-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  width: 84px;
}

.chart-value {
  font-size: 13px;
  color: #2f6fed;
  font-weight: 600;
  margin-bottom: 4px;
}

.chart-bar-wrap {
  flex: 1;
  width: 34px;
  display: flex;
  align-items: flex-end;
  background: #f1f4f9;
  border-radius: 6px;
  overflow: hidden;
}

.chart-bar {
  width: 100%;
  background: linear-gradient(180deg, #61a3ff, #2f6fed);
  border-radius: 6px 6px 0 0;
  transition: height 0.4s;
}

.chart-label {
  font-size: 12px;
  color: #7b8798;
  margin-top: 6px;
  text-align: center;
}

.pass {
  color: #12a150;
}

.fail {
  color: #e5484d;
}
</style>
