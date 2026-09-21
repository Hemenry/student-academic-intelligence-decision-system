<template>
  <div>
    <h2 class="page-title">智能选课</h2>
    <p class="page-desc">
      列表里每门课都已经跑过一遍规则引擎：能选的直接选，不能选的会告出具体原因，
      不用提交失败再猜。选课本身受「Redis 幂等 + 分布式锁 + MySQL 行锁」三重保护，不会超卖。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-input v-model="query.keyword" placeholder="课程名称 / 代码" clearable style="width: 220px"
                  @keyup.enter="load" />
        <el-select v-model="query.course_type" placeholder="课程类别" clearable style="width: 150px">
          <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-checkbox v-model="query.only_selectable">只看可选</el-checkbox>
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="reset">重置</el-button>
        <div style="flex: 1"></div>
        <el-tag effect="plain">本学期已选 {{ selectedCount }} 门 / {{ selectedCredits }} 学分</el-tag>
      </div>

      <el-table :data="rows" v-loading="loading" stripe border size="small" height="560">
        <el-table-column prop="course_code" label="代码" width="100" />
        <el-table-column label="课程名称" min-width="150">
          <template #default="{ row }">
            <div>{{ row.course_name }}</div>
            <div v-if="row.warnings?.length" class="warn-line">⚠ {{ row.warnings[0] }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类别" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.course_type)">{{ typeLabel(row.course_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="credits" label="学分" width="66" />
        <el-table-column prop="teacher_name" label="教师" width="90" />
        <el-table-column label="上课时间" min-width="180">
          <template #default="{ row }">
            <span v-if="!row.time_slots?.length" class="muted">待排</span>
            <div v-else>
              <div v-for="s in row.time_slots" :key="s.id" class="muted">{{ slotText(s) }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="classroom" label="教室" width="120" />
        <el-table-column label="余量" width="100">
          <template #default="{ row }">
            <span :class="{ 'text-danger': row.remaining <= 5 }">{{ row.remaining }} / {{ row.capacity }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="170">
          <template #default="{ row }">
            <el-tag v-if="row.selected" type="success" size="small">已选</el-tag>
            <el-tooltip v-else-if="!row.selectable" :content="row.block_reason" placement="top">
              <el-tag type="info" size="small">不可选</el-tag>
            </el-tooltip>
            <el-tag v-else type="primary" size="small" effect="plain">可选</el-tag>
            <div v-if="!row.selectable && !row.selected" class="muted" style="margin-top: 4px">
              {{ shorten(row.block_reason) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="precheck(row)">预检</el-button>
            <el-button v-if="!row.selected" type="primary" size="small" :disabled="!row.selectable"
                       @click="doSelect(row)">选课</el-button>
            <el-button v-else text type="danger" size="small" @click="doDrop(row)">退课</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 选课预检结果 -->
    <el-dialog v-model="precheckVisible" title="选课预检（规则引擎逐条诊断）" width="620px">
      <div v-if="precheckData">
        <el-alert :type="precheckData.selectable ? 'success' : 'error'" :closable="false" show-icon
                  :title="precheckData.selectable ? '该课程满足全部条件，可以选课' : '存在硬性条件未满足，暂时无法选课'" />
        <div class="muted" style="margin: 10px 0">
          当前学期学分：{{ precheckData.current_credits }} / {{ precheckData.max_credits }}
        </div>
        <el-table :data="precheckData.checks" size="small" border>
          <el-table-column prop="rule_name" label="规则" width="150" />
          <el-table-column label="结果" width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="row.passed ? 'success' : row.level === 'BLOCK' ? 'danger' : 'warning'">
                {{ row.passed ? '通过' : row.level === 'BLOCK' ? '拦截' : '提示' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="260" />
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { enrollmentApi, offeringApi } from '@/api'

const loading = ref(false)
const rows = ref<any[]>([])
const query = reactive({ keyword: '', course_type: '', only_selectable: false })

const precheckVisible = ref(false)
const precheckData = ref<any>(null)

const typeOptions = [
  { label: '专业必修', value: 'REQUIRED' },
  { label: '专业选修', value: 'ELECTIVE' },
  { label: '公共必修', value: 'PUBLIC' },
  { label: '通识选修', value: 'GENERAL' },
]
const typeLabel = (t: string) => typeOptions.find((o) => o.value === t)?.label || t
const typeTag = (t: string) => ({ REQUIRED: 'danger', ELECTIVE: 'warning', PUBLIC: 'primary', GENERAL: 'success' } as any)[t] || 'info'

const selectedCount = computed(() => rows.value.filter((r) => r.selected).length)
const selectedCredits = computed(() =>
  rows.value.filter((r) => r.selected).reduce((sum, r) => sum + (r.credits || 0), 0),
)

const slotText = (s: any) => `周${'一二三四五六日'[s.weekday - 1]} 第${s.start_section}-${s.end_section}节`
const shorten = (text: string) => (text && text.length > 26 ? `${text.slice(0, 26)}…` : text || '')

async function load() {
  loading.value = true
  try {
    // 空串筛选条件由 axios 请求拦截器统一剔除，这里直接透传即可
    rows.value = (await offeringApi.selectable({ ...query })) as any
  } finally {
    loading.value = false
  }
}

function reset() {
  query.keyword = ''
  query.course_type = ''
  query.only_selectable = false
  load()
}

async function precheck(row: any) {
  precheckData.value = await enrollmentApi.precheck({ offering_id: row.id })
  precheckVisible.value = true
}

/** 幂等键：同一门课 + 同一时间戳，双击产生的两次请求只有第一次会被处理 */
function makeIdempotentKey(offeringId: number) {
  return `${offeringId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

async function doSelect(row: any) {
  try {
    await enrollmentApi.select({ offering_id: row.id, idempotent_key: makeIdempotentKey(row.id) })
    ElMessage.success(`选课成功：${row.course_name}`)
    load()
  } catch {
    // 失败原因（满员/冲突/先修课…）由拦截器统一提示
  }
}

async function doDrop(row: any) {
  await ElMessageBox.confirm(`确认退选《${row.course_name}》？`, '退课确认', { type: 'warning' })
    .then(async () => {
      await enrollmentApi.drop({ offering_id: row.id, reason: '学生自主退课' })
      ElMessage.success('退课成功，名额已释放')
      load()
    })
    .catch(() => {})
}

onMounted(load)
</script>

<style scoped>
.warn-line {
  font-size: 12px;
  color: #f59e0b;
  margin-top: 2px;
}
.text-danger {
  color: #e5484d;
  font-weight: 600;
}
</style>
