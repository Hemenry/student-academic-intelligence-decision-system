<template>
  <div>
    <h2 class="page-title">成绩录入</h2>
    <p class="page-desc">
      选择教学班后拉取花名册，录入平时/期末成绩，总评按权重自动计算（默认平时 40% + 期末 60%），
      绩点按 4.0 分制分段映射。批量保存时单条失败不影响其他记录。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-select v-model="semesterId" placeholder="选择学期" style="width: 220px" @change="loadOfferings">
          <el-option v-for="s in semesters" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-select v-model="offeringId" filterable placeholder="选择教学班" style="width: 340px" @change="loadRoster">
          <el-option v-for="o in offerings" :key="o.id"
                     :label="`${o.course_name}（${o.course_code}）· ${o.class_name} · ${o.teacher_name || '教师待定'}`"
                     :value="o.id" />
        </el-select>
        <el-input-number v-model="usualWeight" :min="0" :max="1" :step="0.1" :precision="1"
                         style="width: 140px" />
        <span class="muted">平时成绩权重（期末 {{ (1 - usualWeight).toFixed(1) }}）</span>
        <div style="flex: 1"></div>
        <el-button type="primary" :disabled="!roster.length" :loading="saving" @click="saveAll">
          批量保存（{{ roster.length }} 人）
        </el-button>
      </div>

      <el-table :data="roster" v-loading="loading" border stripe size="small" height="560">
        <el-table-column type="index" label="#" width="55" />
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column prop="student_name" label="姓名" width="110" />
        <el-table-column label="平时成绩" width="150">
          <template #default="{ row }">
            <el-input-number v-model="row.usual_score" :min="0" :max="100" :precision="1" size="small"
                             controls-position="right" style="width: 120px" @change="recalc(row)" />
          </template>
        </el-table-column>
        <el-table-column label="期末成绩" width="150">
          <template #default="{ row }">
            <el-input-number v-model="row.exam_score" :min="0" :max="100" :precision="1" size="small"
                             controls-position="right" style="width: 120px" @change="recalc(row)" />
          </template>
        </el-table-column>
        <el-table-column label="总评（自动）" width="120">
          <template #default="{ row }">
            <b :class="(row.final_score ?? 0) >= 60 ? 'pass' : 'fail'">{{ row.final_score ?? '—' }}</b>
          </template>
        </el-table-column>
        <el-table-column label="绩点" width="80">
          <template #default="{ row }">{{ row.final_score != null ? point(row.final_score) : '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.final_score == null" size="small" type="info">未录入</el-tag>
            <el-tag v-else size="small" :type="row.final_score >= 60 ? 'success' : 'danger'">
              {{ row.final_score >= 60 ? '通过' : '不及格' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="saveOne(row)">保存</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { gradeApi, offeringApi, semesterApi } from '@/api'

const semesters = ref<any[]>([])
const offerings = ref<any[]>([])
const roster = ref<any[]>([])
const semesterId = ref<number>()
const offeringId = ref<number>()
const usualWeight = ref(0.4)
const loading = ref(false)
const saving = ref(false)

/** 与后端 GRADE_POINT_TABLE 保持一致，用于录入时的即时预览 */
function point(score: number) {
  const table: [number, number][] = [
    [90, 4.0], [85, 3.7], [82, 3.3], [78, 3.0], [75, 2.7],
    [72, 2.3], [68, 2.0], [64, 1.5], [60, 1.0], [0, 0.0],
  ]
  return table.find(([t]) => score >= t)?.[1] ?? 0
}

function recalc(row: any) {
  const u = row.usual_score
  const e = row.exam_score
  if (u == null && e == null) {
    row.final_score = null
  } else if (u != null && e != null) {
    row.final_score = Number((u * usualWeight.value + e * (1 - usualWeight.value)).toFixed(1))
  } else {
    row.final_score = Number((e ?? u).toFixed(1))
  }
}

async function loadOfferings() {
  const data: any = await offeringApi.list({ semester_id: semesterId.value, page: 1, page_size: 200 })
  offerings.value = data.items
  offeringId.value = undefined
  roster.value = []
}

async function loadRoster() {
  if (!offeringId.value) return
  loading.value = true
  try {
    roster.value = (await gradeApi.roster(offeringId.value)) as any
  } finally {
    loading.value = false
  }
}

async function saveOne(row: any) {
  if (row.final_score == null && row.usual_score == null && row.exam_score == null) {
    ElMessage.warning('请至少录入一项成绩')
    return
  }
  await gradeApi.record({
    enrollment_id: row.enrollment_id,
    usual_score: row.usual_score,
    exam_score: row.exam_score,
    final_score: null,
    usual_weight: usualWeight.value,
  })
  ElMessage.success(`已保存：${row.student_name}`)
  await loadRoster()
}

async function saveAll() {
  const items = roster.value
    .filter((r) => r.usual_score != null || r.exam_score != null)
    .map((r) => ({
      enrollment_id: r.enrollment_id,
      usual_score: r.usual_score,
      exam_score: r.exam_score,
      final_score: null,
      usual_weight: usualWeight.value,
    }))
  if (!items.length) {
    ElMessage.warning('没有可保存的成绩')
    return
  }
  saving.value = true
  try {
    const res: any = await gradeApi.batchRecord(items)
    ElMessage.success(`成功 ${res.success} 条，失败 ${res.failed.length} 条`)
    if (res.failed?.length) {
      console.warn('失败明细', res.failed)
    }
    await loadRoster()
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  const list: any = await semesterApi.list()
  semesters.value = list
  semesterId.value = (list.find((s: any) => s.is_current) || list[0])?.id
  await loadOfferings()
})
</script>

<style scoped>
.pass {
  color: #12a150;
}

.fail {
  color: #e5484d;
}
</style>
