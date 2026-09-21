<template>
  <div>
    <h2 class="page-title">学期管理</h2>
    <p class="page-desc">
      「开启选课」会把学期状态切到 SELECTING 并设置选课时间窗口 —— 规则引擎的
      <strong>选课时间窗口</strong>规则据此放行，无需修改任何代码。全局只允许一个"当前学期"。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-button type="primary" @click="openCreate">新增学期</el-button>
        <div style="flex: 1"></div>
        <span class="muted">共 {{ rows.length }} 个学期</span>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe size="small">
        <el-table-column prop="code" label="学期代码" width="130" />
        <el-table-column prop="name" label="学期名称" min-width="190" />
        <el-table-column label="起止日期" width="210">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column label="选课窗口" min-width="230">
          <template #default="{ row }">
            <span v-if="!row.select_start_at" class="muted">未设置</span>
            <span v-else>{{ fmt(row.select_start_at) }} ~ {{ fmt(row.select_end_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前学期" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_current" type="success" size="small">是</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="offering_count" label="教学班" width="90" />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'SELECTING'" text type="primary" size="small" @click="openSelection(row)">
              开启选课
            </el-button>
            <el-button v-else text type="danger" size="small" @click="closeSelection(row)">关闭选课</el-button>
            <el-button text size="small" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="visible" :title="form.id ? '编辑学期' : '新增学期'" width="580px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="学期代码">
          <el-input v-model="form.code" placeholder="如 2026-2027-1" />
        </el-form-item>
        <el-form-item label="学期名称">
          <el-input v-model="form.name" placeholder="如 2026-2027学年第一学期" />
        </el-form-item>
        <el-form-item label="学年"><el-input v-model="form.academic_year" placeholder="如 2026-2027" /></el-form-item>
        <el-form-item label="学期序号">
          <el-radio-group v-model="form.term">
            <el-radio :value="1">第一学期（秋）</el-radio>
            <el-radio :value="2">第二学期（春）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="起止日期">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="计划中" value="PLANNING" />
            <el-option label="选课中" value="SELECTING" />
            <el-option label="学期进行中" value="ONGOING" />
            <el-option label="已结束" value="FINISHED" />
          </el-select>
        </el-form-item>
        <el-form-item label="设为当前学期"><el-switch v-model="form.is_current" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="selectionVisible" title="开启选课" width="520px">
      <p class="muted" style="margin-top: 0">设置选课时间窗口，学生在窗口外提交会被「选课时间窗口」规则拦截。</p>
      <el-form label-width="100px">
        <el-form-item label="开始时间">
          <el-date-picker v-model="selectionForm.select_start_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss"
                          style="width: 100%" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-date-picker v-model="selectionForm.select_end_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss"
                          style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="selectionVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="confirmSelection">确认开启</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { semesterApi } from '@/api'

const rows = ref<any[]>([])
const loading = ref(false)
const saving = ref(false)
const visible = ref(false)
const selectionVisible = ref(false)
const dateRange = ref<string[]>([])
const form = reactive<Record<string, any>>({})
const selectionForm = reactive<Record<string, any>>({})
const currentSemester = ref<any>(null)

const statusLabel = (s: string) =>
  ({ PLANNING: '计划中', SELECTING: '选课中', ONGOING: '进行中', FINISHED: '已结束' } as any)[s] || s
const statusTag = (s: string) =>
  ({ PLANNING: 'info', SELECTING: 'primary', ONGOING: 'warning', FINISHED: 'success' } as any)[s] || 'info'
const fmt = (t: string) => (t ? t.replace('T', ' ').slice(0, 16) : '—')

async function load() {
  loading.value = true
  try {
    rows.value = (await semesterApi.list()) as any
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    id: null, code: '', name: '', academic_year: '', term: 1, status: 'PLANNING', is_current: false,
  })
  dateRange.value = []
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, row)
  dateRange.value = [row.start_date, row.end_date]
  visible.value = true
}

async function save() {
  if (!dateRange.value?.length) {
    ElMessage.warning('请选择起止日期')
    return
  }
  saving.value = true
  try {
    const payload = { ...form, start_date: dateRange.value[0], end_date: dateRange.value[1] }
    delete payload.id
    delete payload.offering_count
    if (form.id) {
      await semesterApi.update(form.id, payload)
    } else {
      await semesterApi.create(payload)
    }
    ElMessage.success('保存成功')
    visible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function openSelection(row: any) {
  currentSemester.value = row
  const now = new Date()
  const end = new Date(now.getTime() + 21 * 86400000)
  const toLocal = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19)
  selectionForm.select_start_at = row.select_start_at || toLocal(now)
  selectionForm.select_end_at = row.select_end_at || toLocal(end)
  selectionVisible.value = true
}

async function confirmSelection() {
  saving.value = true
  try {
    await semesterApi.openSelection(currentSemester.value.id, { ...selectionForm })
    ElMessage.success('选课已开启，学生现在可以选课了')
    selectionVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function closeSelection(row: any) {
  await ElMessageBox.confirm(`确认关闭「${row.name}」的选课？关闭后学生将无法再提交选课。`, '提示', {
    type: 'warning',
  })
    .then(async () => {
      await semesterApi.closeSelection(row.id)
      ElMessage.success('选课已关闭')
      load()
    })
    .catch(() => {})
}

onMounted(load)
</script>
