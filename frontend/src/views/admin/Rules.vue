<template>
  <div>
    <h2 class="page-title">选课规则</h2>
    <p class="page-desc">
      规则引擎的配置源。这里开关一条规则或调整参数，<strong>改完即刻生效，不需要发版</strong> ——
      比如选课高峰期想把学期学分上限从 30 调到 32，只改 <code>credit_limit</code> 的参数即可。
    </p>

    <div class="card">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 14px"
                title="BLOCK 级别的规则不通过会直接拦截选课；WARN 级别只提示、仍可提交。" />
      <el-table :data="rows" v-loading="loading" border stripe size="small">
        <el-table-column prop="priority" label="优先级" width="90" />
        <el-table-column prop="name" label="规则名称" min-width="160" />
        <el-table-column prop="rule_key" label="规则标识" width="180" />
        <el-table-column label="参数" min-width="220">
          <template #default="{ row }">
            <code class="params">{{ row.params || '{}' }}</code>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" :disabled="row.id < 0" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button text type="primary" size="small" :disabled="row.id < 0" @click="openParams(row)">
              调整参数
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="muted" style="margin-top: 10px">
        注：标识为负数的规则表示数据库中尚未落库的内置规则，重启后端服务会自动补齐。
      </p>
    </div>

    <el-dialog v-model="visible" title="调整规则参数" width="560px">
      <el-form label-width="110px">
        <el-form-item label="规则">
          <span>{{ current?.name }}（{{ current?.rule_key }}）</span>
        </el-form-item>
        <el-form-item label="参数(JSON)">
          <el-input v-model="paramsText" type="textarea" :rows="6" spellcheck="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveParams">保存并生效</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { analysisApi } from '@/api'

const rows = ref<any[]>([])
const loading = ref(false)
const saving = ref(false)
const visible = ref(false)
const current = ref<any>(null)
const paramsText = ref('{}')

async function load() {
  loading.value = true
  try {
    rows.value = (await analysisApi.rules()) as any
  } finally {
    loading.value = false
  }
}

async function toggle(row: any) {
  try {
    await analysisApi.updateRule(row.id, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '规则已启用' : '规则已停用，缓存已刷新')
    await load()
  } catch {
    row.enabled = !row.enabled
  }
}

function openParams(row: any) {
  current.value = row
  try {
    const parsed = JSON.parse(row.params || '{}')
    paramsText.value = JSON.stringify(parsed, null, 2)
  } catch {
    paramsText.value = row.params || '{}'
  }
  visible.value = true
}

async function saveParams() {
  let params: any
  try {
    params = JSON.parse(paramsText.value)
  } catch {
    ElMessage.error('参数不是合法的 JSON，请检查格式')
    return
  }
  saving.value = true
  try {
    await analysisApi.updateRule(current.value.id, { enabled: current.value.enabled, params })
    ElMessage.success('参数已保存，推荐与选课缓存已失效')
    visible.value = false
    load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.params {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  color: #35476b;
  background: #f5f7fb;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
