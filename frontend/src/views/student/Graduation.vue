<template>
  <div>
    <h2 class="page-title">毕业进度</h2>
    <p class="page-desc">
      以专业培养方案为基准，按课程类别拆分学分完成度，并列出尚未通过的专业必修课，
      最后结合剩余学期给出「能否按期毕业」的研判。
    </p>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">总学分进度</div>
        <div class="stat-value brand">{{ data.progress_percent ?? 0 }}%</div>
        <div class="stat-hint">{{ data.earned_total ?? 0 }} / {{ data.required_total ?? 0 }} 学分</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">当前学期序位</div>
        <div class="stat-value">第 {{ data.semester_index ?? '—' }} 学期</div>
        <div class="stat-hint">标准学制 8 个学期</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">累计 GPA</div>
        <div class="stat-value">{{ data.gpa ?? '—' }}</div>
        <div class="stat-hint">{{ data.major_name }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">毕业研判</div>
        <div class="stat-value" :class="statusClass" style="font-size: 20px">{{ data.estimated_status || '—' }}</div>
        <div class="stat-hint">基于修读速度线性外推</div>
      </div>
    </div>

    <div class="card">
      <h3 class="sec-title">分类别学分完成度</h3>
      <div v-for="row in data.by_type || []" :key="row.course_type" class="type-row">
        <div class="type-head">
          <span>{{ row.label }}</span>
          <span class="muted">{{ row.earned_credits }} / {{ row.required_credits }} 学分
            <b v-if="row.gap > 0" style="color: #e5484d">（缺 {{ row.gap }}）</b>
            <b v-else style="color: #12a150">（已达标）</b>
          </span>
        </div>
        <el-progress :percentage="row.percent" :stroke-width="12"
                     :status="row.gap > 0 ? 'warning' : 'success'" />
      </div>
      <el-alert type="info" :closable="false" show-icon style="margin-top: 16px"
                :title="data.suggestion || '暂无建议'" />
    </div>

    <div class="card">
      <h3 class="sec-title">待完成专业必修课（{{ (data.missing_required_courses || []).length }} 门）</h3>
      <el-table :data="data.missing_required_courses || []" size="small" border stripe>
        <el-table-column prop="course_code" label="代码" width="110" />
        <el-table-column prop="course_name" label="课程名称" min-width="180" />
        <el-table-column prop="credits" label="学分" width="80" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === '修读中' ? 'primary' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="建议" min-width="220">
          <template #default="{ row }">
            <span class="muted">
              {{ row.status === '修读中' ? '本学期修读中，通过后即可计入' : '建议在下一学期优先选课' }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { analysisApi } from '@/api'

const data = ref<Record<string, any>>({})

const statusClass = computed(() => {
  const s = data.value.estimated_status || ''
  if (s.includes('风险') || s.includes('延期')) return 'danger'
  if (s.includes('加速')) return ''
  return 'success'
})

onMounted(async () => {
  data.value = (await analysisApi.graduation()) as any
})
</script>

<style scoped>
.sec-title {
  font-size: 14px;
  margin: 0 0 14px;
  color: #2c3a52;
}

.type-row {
  margin-bottom: 16px;
}

.type-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 6px;
}
</style>
