<template>
  <div>
    <h2 class="page-title">班级管理</h2>
    <p class="page-desc">按专业 + 入学年级划分行政班，班级是班级排名、辅导员跟进、批量风险扫描的统计单位。</p>

    <div class="card">
      <div class="toolbar">
        <el-select v-model="filters.major_id" placeholder="全部专业" clearable style="width: 200px" @change="load">
          <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-select v-model="filters.grade_year" placeholder="全部年级" clearable style="width: 140px" @change="load">
          <el-option v-for="y in [2024, 2025, 2026, 2027]" :key="y" :label="`${y} 级`" :value="y" />
        </el-select>
        <el-button type="primary" @click="openCreate">新增班级</el-button>
        <div style="flex: 1"></div>
        <span class="muted">共 {{ rows.length }} 个班级</span>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe size="small">
        <el-table-column prop="name" label="班级名称" min-width="150" />
        <el-table-column prop="major_name" label="所属专业" min-width="170" />
        <el-table-column prop="grade_year" label="入学年份" width="100" />
        <el-table-column prop="student_count" label="学生数" width="90" />
        <el-table-column prop="counselor" label="辅导员" width="110" />
        <el-table-column prop="remark" label="备注" min-width="140" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="visible" :title="form.id ? '编辑班级' : '新增班级'" width="480px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="班级名称"><el-input v-model="form.name" placeholder="如 计算机2401" /></el-form-item>
        <el-form-item label="所属专业">
          <el-select v-model="form.major_id" style="width: 100%">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="入学年份">
          <el-input-number v-model="form.grade_year" :min="2000" :max="2100" />
        </el-form-item>
        <el-form-item label="辅导员"><el-input v-model="form.counselor" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
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
import { orgApi } from '@/api'

const rows = ref<any[]>([])
const majors = ref<any[]>([])
const loading = ref(false)
const visible = ref(false)
const saving = ref(false)
const filters = reactive<Record<string, any>>({ major_id: undefined, grade_year: undefined })
const form = reactive<Record<string, any>>({})

async function load() {
  loading.value = true
  try {
    rows.value = (await orgApi.classes({ ...filters })) as any
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { id: null, name: '', major_id: majors.value[0]?.id, grade_year: 2026, counselor: '', remark: '' })
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, row)
  visible.value = true
}

async function save() {
  if (!form.name || !form.major_id) {
    ElMessage.warning('请填写班级名称并选择专业')
    return
  }
  saving.value = true
  try {
    const payload = { ...form }
    delete payload.id
    delete payload.major_name
    delete payload.student_count
    if (form.id) {
      await orgApi.updateClass(form.id, payload)
    } else {
      await orgApi.createClass(payload)
    }
    ElMessage.success('保存成功')
    visible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确认删除班级「${row.name}」？`, '危险操作', { type: 'warning' })
    .then(async () => {
      await orgApi.deleteClass(row.id)
      ElMessage.success('已删除')
      load()
    })
    .catch(() => {})
}

onMounted(async () => {
  majors.value = (await orgApi.majors()) as any
  await load()
})
</script>
