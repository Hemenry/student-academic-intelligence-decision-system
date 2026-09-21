<template>
  <div>
    <h2 class="page-title">专业管理</h2>
    <p class="page-desc">
      专业是培养方案的载体：毕业总学分、学制都挂在专业上，学生的毕业进度分析以此为基准。
      专业下若有学生则不允许删除，避免产生"孤儿数据"。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-button type="primary" @click="openCreate">新增专业</el-button>
        <div style="flex: 1"></div>
        <span class="muted">共 {{ rows.length }} 个专业</span>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe size="small">
        <el-table-column prop="code" label="专业代码" width="120" />
        <el-table-column prop="name" label="专业名称" min-width="180" />
        <el-table-column prop="college" label="所属学院" min-width="150" />
        <el-table-column prop="duration_years" label="学制(年)" width="90" />
        <el-table-column prop="total_credits" label="毕业总学分" width="110" />
        <el-table-column prop="degree" label="授予学位" width="120" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="visible" :title="form.id ? '编辑专业' : '新增专业'" width="480px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="专业代码"><el-input v-model="form.code" placeholder="如 CS" /></el-form-item>
        <el-form-item label="专业名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="所属学院"><el-input v-model="form.college" /></el-form-item>
        <el-form-item label="学制(年)"><el-input-number v-model="form.duration_years" :min="2" :max="8" /></el-form-item>
        <el-form-item label="毕业总学分"><el-input-number v-model="form.total_credits" :min="60" :max="260" /></el-form-item>
        <el-form-item label="授予学位"><el-input v-model="form.degree" /></el-form-item>
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
const loading = ref(false)
const visible = ref(false)
const saving = ref(false)
const form = reactive<Record<string, any>>({})

async function load() {
  loading.value = true
  try {
    rows.value = (await orgApi.majors()) as any
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { id: null, code: '', name: '', college: '', duration_years: 4, total_credits: 160, degree: '工学学士' })
  visible.value = true
}

function openEdit(row: any) {
  Object.assign(form, row)
  visible.value = true
}

async function save() {
  saving.value = true
  try {
    const payload = { ...form }
    delete payload.id
    if (form.id) {
      await orgApi.updateMajor(form.id, payload)
    } else {
      await orgApi.createMajor(payload)
    }
    ElMessage.success('保存成功')
    visible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确认删除专业「${row.name}」？该操作不可恢复。`, '危险操作', { type: 'warning' })
    .then(async () => {
      await orgApi.deleteMajor(row.id)
      ElMessage.success('已删除')
      load()
    })
    .catch(() => {})
}

onMounted(load)
</script>
