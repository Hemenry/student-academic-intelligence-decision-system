<template>
  <div>
    <h2 class="page-title">课程库</h2>
    <p class="page-desc">
      课程库是教学大纲层面的"课"，与学期无关；每学期再基于课程开出教学班。
      先修课关系配置在这里，直接参与选课规则引擎的「先修课校验」。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-input v-model="filters.keyword" placeholder="课程名 / 代码" clearable style="width: 200px"
                  @keyup.enter="load" />
        <el-select v-model="filters.course_type" placeholder="全部类别" clearable style="width: 150px" @change="load">
          <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="openCreate">新增课程</el-button>
        <div style="flex: 1"></div>
        <span class="muted">共 {{ total }} 门课程</span>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe size="small" height="580">
        <el-table-column prop="code" label="课程代码" width="110" />
        <el-table-column prop="name" label="课程名称" min-width="160" />
        <el-table-column label="类别" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.course_type)">{{ typeLabel(row.course_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="credits" label="学分" width="66" />
        <el-table-column prop="hours" label="学时" width="66" />
        <el-table-column prop="college" label="开课学院" width="150" />
        <el-table-column label="先修课" min-width="180">
          <template #default="{ row }">
            <span v-if="!row.prerequisite_names?.length" class="muted">无</span>
            <el-tag v-for="n in row.prerequisite_names" :key="n" size="small" effect="plain" style="margin-right: 4px">
              {{ n }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text size="small" @click="openPrereq(row)">先修课</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination style="margin-top: 14px" layout="total, prev, pager, next" :total="total"
                     :page-size="filters.page_size" :current-page="filters.page" @current-change="onPage" />
    </div>

    <!-- 课程表单 -->
    <el-dialog v-model="visible" :title="form.id ? '编辑课程' : '新增课程'" width="560px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="课程代码"><el-input v-model="form.code" /></el-form-item>
        <el-form-item label="课程名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="学分">
          <el-input-number v-model="form.credits" :min="0.5" :max="20" :step="0.5" />
        </el-form-item>
        <el-form-item label="总学时"><el-input-number v-model="form.hours" :min="8" :max="200" :step="8" /></el-form-item>
        <el-form-item label="课程类别">
          <el-select v-model="form.course_type" style="width: 100%">
            <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="开课学院"><el-input v-model="form.college" /></el-form-item>
        <el-form-item label="适用专业">
          <el-select v-model="scopeList" multiple collapse-tags placeholder="留空表示全校可选" style="width: 100%">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="课程简介">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="是否启用"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 先修课配置 -->
    <el-dialog v-model="prereqVisible" title="配置先修课" width="620px">
      <p class="muted" style="margin-top: 0">
        为《{{ current?.name }}》指定先修课程与最低分数要求。学生在选课时若未修读或未达标，会被规则引擎直接拦截。
      </p>
      <div class="toolbar">
        <el-select v-model="newPrereq.prerequisite_course_id" filterable placeholder="选择先修课程" style="width: 300px">
          <el-option v-for="c in otherCourses" :key="c.id" :label="`${c.name}（${c.code}）`" :value="c.id" />
        </el-select>
        <el-input-number v-model="newPrereq.min_score" :min="0" :max="100" style="width: 120px" />
        <el-button type="primary" @click="addPrereq">添加</el-button>
      </div>
      <el-table :data="prereqList" size="small" border>
        <el-table-column label="先修课程" min-width="200">
          <template #default="{ row }">{{ courseName(row.prerequisite_course_id) }}</template>
        </el-table-column>
        <el-table-column label="最低分数" width="140">
          <template #default="{ row }">
            <el-input-number v-model="row.min_score" :min="0" :max="100" size="small" controls-position="right" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ $index }">
            <el-button text type="danger" size="small" @click="prereqList.splice($index, 1)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="prereqVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePrereq">保存配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { courseApi, orgApi } from '@/api'

const rows = ref<any[]>([])
const allCourses = ref<any[]>([])
const majors = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const visible = ref(false)
const saving = ref(false)
const prereqVisible = ref(false)
const current = ref<any>(null)
const prereqList = ref<any[]>([])
const newPrereq = reactive<Record<string, any>>({ prerequisite_course_id: undefined, min_score: 60 })
const filters = reactive<Record<string, any>>({ keyword: '', course_type: '', page: 1, page_size: 20 })
const form = reactive<Record<string, any>>({})
const scopeList = ref<number[]>([])

const typeOptions = [
  { label: '专业必修', value: 'REQUIRED' },
  { label: '专业选修', value: 'ELECTIVE' },
  { label: '公共必修', value: 'PUBLIC' },
  { label: '通识选修', value: 'GENERAL' },
]
const typeLabel = (t: string) => typeOptions.find((o) => o.value === t)?.label || t
const typeTag = (t: string) => ({ REQUIRED: 'danger', ELECTIVE: 'warning', PUBLIC: 'primary', GENERAL: 'success' } as any)[t] || 'info'

const otherCourses = computed(() => allCourses.value.filter((c) => c.id !== current.value?.id))
const courseName = (id: number) => allCourses.value.find((c) => c.id === id)?.name || `课程#${id}`

async function load() {
  loading.value = true
  try {
    const data: any = await courseApi.list({ ...filters })
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

function openCreate() {
  Object.assign(form, { id: null, code: '', name: '', credits: 3, hours: 48, course_type: 'REQUIRED', college: '', description: '', is_active: true })
  scopeList.value = []
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, row)
  scopeList.value = row.major_scope ? row.major_scope.split(',').map((s: string) => Number(s)) : []
  visible.value = true
}

async function save() {
  saving.value = true
  try {
    const payload = { ...form, major_scope: scopeList.value.length ? scopeList.value.join(',') : null }
    delete payload.id
    delete payload.prerequisite_names
    if (form.id) {
      await courseApi.update(form.id, payload)
    } else {
      await courseApi.create(payload)
    }
    ElMessage.success('保存成功')
    visible.value = false
    await refreshAll()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确认删除课程「${row.name}」？已有开课记录的课程不允许删除。`, '危险操作', {
    type: 'warning',
  })
    .then(async () => {
      await courseApi.delete(row.id)
      ElMessage.success('已删除')
      await refreshAll()
    })
    .catch(() => {})
}

async function openPrereq(row: any) {
  current.value = row
  const detail: any = await courseApi.detail(row.id)
  // 后端详情接口直接返回结构化先修课（含最低分数），无需再用课程名反查
  prereqList.value = (detail.prerequisites || []).map((p: any) => ({
    prerequisite_course_id: p.prerequisite_course_id,
    min_score: p.min_score,
    allow_concurrent: p.allow_concurrent,
  }))
  newPrereq.prerequisite_course_id = undefined
  newPrereq.min_score = 60
  prereqVisible.value = true
}

function addPrereq() {
  if (!newPrereq.prerequisite_course_id) {
    ElMessage.warning('请选择先修课程')
    return
  }
  prereqList.value.push({ ...newPrereq })
  newPrereq.prerequisite_course_id = undefined
}

async function savePrereq() {
  saving.value = true
  try {
    await courseApi.setPrerequisites(current.value.id, prereqList.value)
    ElMessage.success('先修课配置已保存')
    prereqVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function refreshAll() {
  const all: any = await courseApi.list({ page: 1, page_size: 200 })
  allCourses.value = all.items
  await load()
}

onMounted(async () => {
  majors.value = (await orgApi.majors()) as any
  await refreshAll()
})
</script>
