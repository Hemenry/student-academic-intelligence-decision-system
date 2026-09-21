<template>
  <div>
    <h2 class="page-title">开课计划</h2>
    <p class="page-desc">
      教学班是选课的最小单位（课程 + 学期 + 教师 + 容量 + 时间地点）。
      容量即"库存"，<code>selected_count</code> 由选课事务加行锁扣减，是防超卖的关键字段。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-select v-model="filters.semester_id" placeholder="全部学期" clearable style="width: 220px" @change="load">
          <el-option v-for="s in semesters" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-input v-model="filters.keyword" placeholder="课程名 / 代码" clearable style="width: 180px"
                  @keyup.enter="load" />
        <el-select v-model="filters.course_type" placeholder="全部类别" clearable style="width: 140px" @change="load">
          <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="openCreate">新增开课</el-button>
        <div style="flex: 1"></div>
        <span class="muted">共 {{ total }} 个教学班</span>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe size="small" height="560">
        <el-table-column prop="course_code" label="代码" width="100" />
        <el-table-column prop="course_name" label="课程名称" min-width="150" />
        <el-table-column label="类别" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.course_type)">{{ typeLabel(row.course_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="credits" label="学分" width="60" />
        <el-table-column prop="semester_code" label="学期" width="110" />
        <el-table-column prop="teacher_name" label="教师" width="90" />
        <el-table-column prop="class_name" label="教学班" width="100" />
        <el-table-column label="上课时间" min-width="190">
          <template #default="{ row }">
            <span v-if="!row.time_slots?.length" class="muted">未排课</span>
            <div v-else>
              <div v-for="s in row.time_slots" :key="s.id" class="muted">{{ slotText(s) }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="classroom" label="教室" width="110" />
        <el-table-column label="选课情况" width="150">
          <template #default="{ row }">
            <div class="muted">{{ row.selected_count }} / {{ row.capacity }}（余 {{ row.remaining }}）</div>
            <el-progress :percentage="percent(row)" :stroke-width="6" :show-text="false"
                         :status="percent(row) >= 100 ? 'exception' : undefined" />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_open ? 'success' : 'info'">{{ row.is_open ? '开放' : '关闭' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination style="margin-top: 14px" layout="total, prev, pager, next" :total="total"
                     :page-size="filters.page_size" :current-page="filters.page" @current-change="onPage" />
    </div>

    <el-dialog v-model="visible" :title="form.id ? '编辑开课计划' : '新增开课计划'" width="700px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="课程">
          <el-select v-model="form.course_id" filterable :disabled="!!form.id" style="width: 100%" placeholder="选择课程">
            <el-option v-for="c in courses" :key="c.id" :label="`${c.name}（${c.code} / ${c.credits}学分）`" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="学期">
          <el-select v-model="form.semester_id" :disabled="!!form.id" style="width: 100%">
            <el-option v-for="s in semesters" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="授课教师">
          <el-select v-model="form.teacher_id" clearable style="width: 100%">
            <el-option v-for="t in teachers" :key="t.id" :label="`${t.name}（${t.title}）`" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="教学班名称"><el-input v-model="form.class_name" placeholder="如 01班" /></el-form-item>
        <el-form-item label="课容量">
          <el-input-number v-model="form.capacity" :min="1" :max="1000" />
          <span v-if="form.id" class="muted" style="margin-left: 10px">
            当前已选 {{ form.selected_count }} 人，容量不能小于该值
          </span>
        </el-form-item>
        <el-form-item label="校区 / 教室">
          <el-input v-model="form.campus" style="width: 45%" placeholder="校区" />
          <el-input v-model="form.classroom" style="width: 45%; margin-left: 10px" placeholder="教室" />
        </el-form-item>
        <el-form-item label="面向专业">
          <el-select v-model="scopeList" multiple collapse-tags placeholder="留空表示全校可选" style="width: 100%">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="是否开放"><el-switch v-model="form.is_open" /></el-form-item>

        <el-form-item label="上课时间">
          <div class="slot-editor">
            <div v-for="(slot, idx) in form.time_slots" :key="idx" class="slot-row">
              <el-select v-model="slot.weekday" style="width: 100px">
                <el-option v-for="d in 7" :key="d" :label="`周${'一二三四五六日'[d - 1]}`" :value="d" />
              </el-select>
              <el-select v-model="slot.start_section" style="width: 96px">
                <el-option v-for="s in 12" :key="s" :label="`第${s}节`" :value="s" />
              </el-select>
              <span class="muted">到</span>
              <el-select v-model="slot.end_section" style="width: 96px">
                <el-option v-for="s in 12" :key="s" :label="`第${s}节`" :value="s" />
              </el-select>
              <el-select v-model="slot.start_week" style="width: 96px">
                <el-option v-for="w in 20" :key="w" :label="`第${w}周`" :value="w" />
              </el-select>
              <span class="muted">到</span>
              <el-select v-model="slot.end_week" style="width: 96px">
                <el-option v-for="w in 20" :key="w" :label="`第${w}周`" :value="w" />
              </el-select>
              <el-button text type="danger" size="small" @click="form.time_slots.splice(idx, 1)">删除</el-button>
            </div>
            <el-button size="small" @click="addSlot">+ 添加时间段</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { courseApi, offeringApi, orgApi, semesterApi } from '@/api'

const rows = ref<any[]>([])
const courses = ref<any[]>([])
const semesters = ref<any[]>([])
const majors = ref<any[]>([])
const teachers = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const visible = ref(false)
const saving = ref(false)
const scopeList = ref<number[]>([])
const filters = reactive<Record<string, any>>({
  semester_id: undefined, keyword: '', course_type: '', page: 1, page_size: 20,
})
const form = reactive<Record<string, any>>({ time_slots: [] })

const typeOptions = [
  { label: '专业必修', value: 'REQUIRED' },
  { label: '专业选修', value: 'ELECTIVE' },
  { label: '公共必修', value: 'PUBLIC' },
  { label: '通识选修', value: 'GENERAL' },
]
const typeLabel = (t: string) => typeOptions.find((o) => o.value === t)?.label || t
const typeTag = (t: string) => ({ REQUIRED: 'danger', ELECTIVE: 'warning', PUBLIC: 'primary', GENERAL: 'success' } as any)[t] || 'info'
const slotText = (s: any) =>
  `周${'一二三四五六日'[s.weekday - 1]}第${s.start_section}-${s.end_section}节 ${s.start_week}-${s.end_week}周`
const percent = (row: any) => Math.min(Math.round((row.selected_count / (row.capacity || 1)) * 100), 100)

async function load() {
  loading.value = true
  try {
    const data: any = await offeringApi.list({ ...filters })
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

function addSlot() {
  form.time_slots.push({ weekday: 1, start_section: 1, end_section: 2, start_week: 1, end_week: 16 })
}

function openCreate() {
  Object.assign(form, {
    id: null, course_id: undefined, semester_id: semesters.value.find((s) => s.is_current)?.id,
    teacher_id: undefined, class_name: '01班', capacity: 60, campus: '主校区', classroom: '待定',
    is_open: true, time_slots: [{ weekday: 1, start_section: 1, end_section: 2, start_week: 1, end_week: 16 }],
  })
  scopeList.value = []
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, { ...row, time_slots: (row.time_slots || []).map((s: any) => ({ ...s })) })
  scopeList.value = row.major_scope ? row.major_scope.split(',').map((s: string) => Number(s)) : []
  visible.value = true
}

async function save() {
  if (!form.course_id || !form.semester_id) {
    ElMessage.warning('请选择课程与学期')
    return
  }
  saving.value = true
  try {
    const payload: Record<string, any> = {
      teacher_id: form.teacher_id,
      class_name: form.class_name,
      capacity: form.capacity,
      campus: form.campus,
      classroom: form.classroom,
      major_scope: scopeList.value.length ? scopeList.value.join(',') : null,
      is_open: form.is_open,
      time_slots: form.time_slots,
    }
    if (form.id) {
      await offeringApi.update(form.id, payload)
    } else {
      await offeringApi.create({ ...payload, course_id: form.course_id, semester_id: form.semester_id })
    }
    ElMessage.success('保存成功')
    visible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(
    `确认删除教学班「${row.course_name} ${row.class_name}」？已有学生选课的教学班不可删除。`,
    '危险操作',
    { type: 'warning' },
  )
    .then(async () => {
      await offeringApi.remove(row.id)
      ElMessage.success('已删除')
      load()
    })
    .catch(() => {})
}

onMounted(async () => {
  const [c, s, m, t] = await Promise.all([
    courseApi.list({ page: 1, page_size: 200 }),
    semesterApi.list(),
    orgApi.majors(),
    orgApi.teachers(),
  ])
  courses.value = (c as any).items
  semesters.value = s as any
  majors.value = m as any
  teachers.value = t as any
  await load()
})
</script>

<style scoped>
.slot-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.slot-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
