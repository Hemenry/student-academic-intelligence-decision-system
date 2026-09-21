<template>
  <div>
    <h2 class="page-title">选课统计</h2>
    <p class="page-desc">
      各教学班的选课率排行。选课率接近 100% 的课程说明学位紧张，教务处可考虑加开班次或扩容；
      选课率过低的课程则要评估是否撤班。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-select v-model="semesterId" placeholder="全部学期" clearable style="width: 220px" @change="load">
          <el-option v-for="s in semesters" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-button type="primary" @click="load">刷新</el-button>
        <div style="flex: 1"></div>
        <el-tag effect="plain">教学班 {{ rows.length }} 个</el-tag>
        <el-tag type="danger" effect="plain">已满 {{ fullCount }} 个</el-tag>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe size="small" height="600">
        <el-table-column type="index" label="排名" width="80" />
        <el-table-column prop="course_code" label="代码" width="110" />
        <el-table-column prop="course_name" label="课程名称" min-width="170" />
        <el-table-column label="类别" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.course_type)">{{ typeLabel(row.course_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="semester_code" label="学期" width="120" />
        <el-table-column prop="teacher_name" label="教师" width="100" />
        <el-table-column prop="capacity" label="容量" width="80" />
        <el-table-column prop="selected_count" label="已选" width="80" />
        <el-table-column prop="remaining" label="余量" width="80">
          <template #default="{ row }">
            <span :class="{ 'text-danger': row.remaining <= 5 }">{{ row.remaining }}</span>
          </template>
        </el-table-column>
        <el-table-column label="选课率" min-width="220" sortable :sort-by="'select_ratio'">
          <template #default="{ row }">
            <div class="ratio">
              <el-progress :percentage="Math.min(row.select_ratio, 100)" :stroke-width="10"
                           :status="row.select_ratio >= 100 ? 'exception' : row.select_ratio >= 80 ? 'warning' : 'success'"
                           :show-text="false" style="flex: 1" />
              <span class="ratio-num">{{ row.select_ratio }}%</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { enrollmentApi, semesterApi } from '@/api'

const rows = ref<any[]>([])
const semesters = ref<any[]>([])
const semesterId = ref<number>()
const loading = ref(false)

const typeOptions = [
  { label: '专业必修', value: 'REQUIRED' },
  { label: '专业选修', value: 'ELECTIVE' },
  { label: '公共必修', value: 'PUBLIC' },
  { label: '通识选修', value: 'GENERAL' },
]
const typeLabel = (t: string) => typeOptions.find((o) => o.value === t)?.label || t
const typeTag = (t: string) => ({ REQUIRED: 'danger', ELECTIVE: 'warning', PUBLIC: 'primary', GENERAL: 'success' } as any)[t] || 'info'
const fullCount = computed(() => rows.value.filter((r) => r.remaining <= 0).length)

async function load() {
  loading.value = true
  try {
    rows.value = (await enrollmentApi.statsByCourse({ semester_id: semesterId.value })) as any
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  semesters.value = (await semesterApi.list()) as any
  const current = semesters.value.find((s: any) => s.is_current) || semesters.value[0]
  semesterId.value = current?.id
  await load()
})
</script>

<style scoped>
.ratio {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ratio-num {
  width: 52px;
  text-align: right;
  font-size: 12px;
  color: #7b8798;
}

.text-danger {
  color: #e5484d;
  font-weight: 600;
}
</style>
