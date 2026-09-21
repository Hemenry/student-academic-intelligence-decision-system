<template>
  <div>
    <h2 class="page-title">学业预警</h2>
    <p class="page-desc">
      扫描会对每位在读学生计算五类风险（挂科 / 绩点 / 学分进度 / 成绩趋势 / 毕业风险），
      加权得到综合风险分并落库。每条预警都带触发原因与干预建议，便于辅导员精准跟进。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-select v-model="scanClassId" placeholder="扫描范围：全部学生" clearable filterable
                   style="width: 240px">
          <el-option v-for="c in classes" :key="c.id" :label="`${c.name}（${c.student_count} 人）`" :value="c.id" />
        </el-select>
        <el-button type="primary" :loading="scanning" @click="doScan">一键扫描</el-button>
        <el-divider direction="vertical" />
        <el-select v-model="filters.risk_level" placeholder="全部等级" clearable style="width: 130px" @change="load">
          <el-option label="高风险" value="HIGH" />
          <el-option label="中风险" value="MEDIUM" />
          <el-option label="低风险" value="LOW" />
        </el-select>
        <el-select v-model="filters.risk_type" placeholder="全部类型" clearable style="width: 160px" @change="load">
          <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-select v-model="filters.status" placeholder="处理状态" clearable style="width: 140px" @change="load">
          <el-option label="待处理" value="OPEN" />
          <el-option label="已处理" value="HANDLED" />
          <el-option label="已忽略" value="IGNORED" />
        </el-select>
        <div style="flex: 1"></div>
        <span class="muted">共 {{ total }} 条</span>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe size="small" height="560">
        <el-table-column label="等级" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="dark" :type="levelTag(row.risk_level)">{{ levelText(row.risk_level) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="risk_score" label="风险分" width="80" sortable />
        <el-table-column prop="student_no" label="学号" width="120" />
        <el-table-column prop="student_name" label="姓名" width="100" />
        <el-table-column label="风险类型" width="130">
          <template #default="{ row }">
            {{ typeLabel(row.risk_type) }}
          </template>
        </el-table-column>
        <el-table-column prop="title" label="风险描述" min-width="180" />
        <el-table-column label="触发原因" min-width="280">
          <template #default="{ row }">
            <ul class="reason-list" style="padding-left: 14px">
              <li v-for="(r, i) in parseReason(row.reason)" :key="i">{{ r }}</li>
            </ul>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'OPEN' ? 'warning' : 'success'">
              {{ row.status === 'OPEN' ? '待处理' : row.status === 'HANDLED' ? '已处理' : '已忽略' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'OPEN'" text type="primary" size="small" @click="handle(row)">
              处理
            </el-button>
            <el-button text size="small" @click="ignore(row)">忽略</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination style="margin-top: 14px" layout="total, prev, pager, next" :total="total"
                     :page-size="filters.page_size" :current-page="filters.page" @current-change="onPage" />
    </div>

    <el-dialog v-model="handleVisible" title="处理学业预警" width="520px">
      <el-form label-width="90px">
        <el-form-item label="学生">
          <span>{{ current?.student_name }}（{{ current?.student_no }}）</span>
        </el-form-item>
        <el-form-item label="风险点">
          <span>{{ current?.title }}</span>
        </el-form-item>
        <el-form-item label="系统建议">
          <span class="muted">{{ current?.suggestion }}</span>
        </el-form-item>
        <el-form-item label="处理记录">
          <el-input v-model="handleNote" type="textarea" :rows="3" placeholder="如：已约谈学生，制定重修计划" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="handleVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="confirmHandle">确认已处理</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { analysisApi, orgApi } from '@/api'

const rows = ref<any[]>([])
const classes = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const scanning = ref(false)
const scanClassId = ref<number>()
const handleVisible = ref(false)
const handleNote = ref('')
const current = ref<any>(null)
const filters = reactive<Record<string, any>>({
  risk_level: undefined, risk_type: undefined, status: 'OPEN', page: 1, page_size: 20,
})

const typeOptions = [
  { label: '挂科风险', value: 'FAILED_COURSE' },
  { label: '绩点预警', value: 'GPA_WARNING' },
  { label: '学分落后', value: 'CREDIT_LAG' },
  { label: '成绩下滑', value: 'TREND_DOWN' },
  { label: '毕业风险', value: 'GRADUATION_RISK' },
]
const typeLabel = (t: string) => typeOptions.find((o) => o.value === t)?.label || t
const levelText = (l: string) => ({ HIGH: '高', MEDIUM: '中', LOW: '低' } as any)[l] || l
const levelTag = (l: string) => ({ HIGH: 'danger', MEDIUM: 'warning', LOW: 'success' } as any)[l] || 'info'

function parseReason(reason: string) {
  if (!reason) return []
  try {
    const parsed = JSON.parse(reason)
    return Array.isArray(parsed) ? parsed : [reason]
  } catch {
    return [reason]
  }
}

async function load() {
  loading.value = true
  try {
    const data: any = await analysisApi.alerts({ ...filters })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onPage(page: number) {
  filters.page = page
  load()
}

async function doScan() {
  scanning.value = true
  try {
    const params: Record<string, any> = { persist: true }
    if (scanClassId.value) params.class_id = scanClassId.value
    const res: any = await analysisApi.riskScan(params)
    ElMessage.success(`扫描完成：命中 ${res.scanned} 人，其中高风险 ${res.high_risk} 人`)
    filters.page = 1
    await load()
  } finally {
    scanning.value = false
  }
}

function handle(row: any) {
  current.value = row
  handleNote.value = ''
  handleVisible.value = true
}

async function confirmHandle() {
  saving.value = true
  try {
    await analysisApi.handleAlert(current.value.id, { status: 'HANDLED', note: handleNote.value })
    ElMessage.success('已标记为处理完成')
    handleVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function ignore(row: any) {
  await analysisApi.handleAlert(row.id, { status: 'IGNORED', note: '管理员忽略' })
  ElMessage.success('已忽略该预警')
  load()
}

onMounted(async () => {
  classes.value = (await orgApi.classes()) as any
  await load()
})
</script>
