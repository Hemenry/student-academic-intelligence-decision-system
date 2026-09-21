<template>
  <div>
    <h2 class="page-title">学生管理</h2>
    <p class="page-desc">
      新增学生时会<strong>在同一个事务里</strong>同时创建登录账号与学籍档案，避免出现"有账号没档案"的脏数据。
      默认密码 123456，建议学生首次登录后自行修改。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-input v-model="filters.keyword" placeholder="学号 / 姓名" clearable style="width: 180px"
                  @keyup.enter="load" />
        <el-select v-model="filters.major_id" placeholder="全部专业" clearable style="width: 180px" @change="load">
          <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-select v-model="filters.grade_year" placeholder="全部年级" clearable style="width: 130px" @change="load">
          <el-option v-for="y in [2024, 2025, 2026]" :key="y" :label="`${y} 级`" :value="y" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="openCreate">新增学生</el-button>
        <div style="flex: 1"></div>
        <span class="muted">共 {{ total }} 名学生</span>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe size="small" height="580">
        <el-table-column prop="student_no" label="学号" width="120" />
        <el-table-column prop="name" label="姓名" width="100" />
        <el-table-column label="性别" width="70">
          <template #default="{ row }">{{ row.gender === 'M' ? '男' : '女' }}</template>
        </el-table-column>
        <el-table-column prop="major_name" label="专业" min-width="160" />
        <el-table-column prop="class_name" label="班级" width="120" />
        <el-table-column prop="enrollment_year" label="入学年份" width="100" />
        <el-table-column label="学籍状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'ENROLLED' ? 'success' : 'info'">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="联系电话" width="130" />
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text size="small" @click="showReport(row)">学业报告</el-button>
            <el-button text type="warning" size="small" @click="resetPwd(row)">重置密码</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination style="margin-top: 14px" layout="total, prev, pager, next" :total="total"
                     :page-size="filters.page_size" :current-page="filters.page" @current-change="onPage" />
    </div>

    <!-- 新增/编辑 -->
    <el-dialog v-model="visible" :title="form.id ? '编辑学生' : '新增学生'" width="600px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="登录账号">
          <el-input v-model="form.username" :disabled="!!form.id" placeholder="一般与学号一致" />
        </el-form-item>
        <el-form-item label="学号"><el-input v-model="form.student_no" :disabled="!!form.id" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="性别">
          <el-radio-group v-model="form.gender">
            <el-radio value="M">男</el-radio>
            <el-radio value="F">女</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="专业">
          <el-select v-model="form.major_id" style="width: 100%" @change="onMajorChange">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="班级">
          <el-select v-model="form.class_id" clearable style="width: 100%">
            <el-option v-for="c in filteredClasses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="入学年份">
          <el-input-number v-model="form.enrollment_year" :min="2000" :max="2100" />
        </el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item v-if="form.id" label="学籍状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="在读" value="ENROLLED" />
            <el-option label="休学" value="SUSPENDED" />
            <el-option label="已毕业" value="GRADUATED" />
            <el-option label="退学" value="DROPPED" />
          </el-select>
        </el-form-item>
        <el-alert v-if="!form.id" type="info" :closable="false" title="初始密码为 123456，请提醒学生首次登录后修改" />
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 学业报告 -->
    <el-drawer v-model="reportVisible" title="学生学业报告" size="640px">
      <div v-if="report" v-loading="reportLoading">
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-label">累计 GPA</div>
            <div class="stat-value brand">{{ report.gpa_stat?.overall_gpa }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">已获学分</div>
            <div class="stat-value">{{ report.gpa_stat?.total_credits_earned }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">风险分</div>
            <div class="stat-value danger">{{ report.risk?.risk_score }}</div>
          </div>
        </div>
        <div class="card" style="margin-top: 16px">
          <h3 style="font-size: 14px; margin: 0 0 10px">毕业进度：{{ report.graduation?.progress_percent }}%</h3>
          <el-progress :percentage="report.graduation?.progress_percent || 0" :stroke-width="12" status="success" />
          <p class="muted" style="line-height: 1.9">{{ report.graduation?.suggestion }}</p>
        </div>
        <div class="card" v-if="report.risk?.findings?.length">
          <h3 style="font-size: 14px; margin: 0 0 10px">风险明细</h3>
          <el-table :data="report.risk.findings" size="small" border>
            <el-table-column label="等级" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.risk_level === 'HIGH' ? 'danger' : 'warning'">
                  {{ row.risk_level }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="风险点" min-width="140" />
            <el-table-column label="原因" min-width="180">
              <template #default="{ row }">{{ row.reasons?.join('；') }}</template>
            </el-table-column>
          </el-table>
        </div>
        <el-empty v-else description="未发现学业风险" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { analysisApi, orgApi, studentApi } from '@/api'

const rows = ref<any[]>([])
const majors = ref<any[]>([])
const classes = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const visible = ref(false)
const reportVisible = ref(false)
const reportLoading = ref(false)
const report = ref<any>(null)
const filters = reactive<Record<string, any>>({
  keyword: '', major_id: undefined, grade_year: undefined, page: 1, page_size: 20,
})
const form = reactive<Record<string, any>>({})

const filteredClasses = computed(() =>
  classes.value.filter((c) => c.major_id === form.major_id),
)

const statusLabel = (s: string) =>
  ({ ENROLLED: '在读', SUSPENDED: '休学', GRADUATED: '已毕业', DROPPED: '退学' } as any)[s] || s

async function load() {
  loading.value = true
  try {
    const data: any = await studentApi.list({ ...filters })
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

function onMajorChange() {
  form.class_id = undefined
}

function openCreate() {
  Object.assign(form, {
    id: null, username: '', student_no: '', name: '', gender: 'M',
    major_id: majors.value[0]?.id, class_id: undefined, enrollment_year: 2026, phone: '', email: '',
  })
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, row)
  visible.value = true
}

async function save() {
  saving.value = true
  try {
    if (form.id) {
      const payload = { ...form }
      delete payload.id
      delete payload.student_no
      delete payload.username
      delete payload.major_name
      delete payload.class_name
      await studentApi.update(form.id, payload)
    } else {
      await studentApi.create({
        username: form.username || form.student_no,
        password: '123456',
        student_no: form.student_no,
        name: form.name,
        gender: form.gender,
        major_id: form.major_id,
        class_id: form.class_id,
        enrollment_year: form.enrollment_year,
        phone: form.phone,
        email: form.email,
      })
    }
    ElMessage.success('保存成功')
    visible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function resetPwd(row: any) {
  await ElMessageBox.confirm(`将「${row.name}」的密码重置为 123456？`, '提示', { type: 'warning' })
    .then(async () => {
      await studentApi.resetPassword(row.id)
      ElMessage.success('密码已重置为 123456')
    })
    .catch(() => {})
}

async function remove(row: any) {
  await ElMessageBox.confirm(
    `确认删除学生「${row.name}」？该学生的选课与成绩记录会一并删除，操作不可恢复。`,
    '危险操作',
    { type: 'warning' },
  )
    .then(async () => {
      await studentApi.remove(row.id)
      ElMessage.success('已删除')
      load()
    })
    .catch(() => {})
}

async function showReport(row: any) {
  reportVisible.value = true
  reportLoading.value = true
  try {
    report.value = await analysisApi.studentReport(row.id)
  } finally {
    reportLoading.value = false
  }
}

onMounted(async () => {
  const [m, c] = await Promise.all([orgApi.majors(), orgApi.classes()])
  majors.value = m as any
  classes.value = c as any
  await load()
})
</script>
