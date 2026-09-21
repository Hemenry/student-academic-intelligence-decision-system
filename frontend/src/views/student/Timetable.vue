<template>
  <div>
    <h2 class="page-title">我的课表</h2>
    <p class="page-desc">
      按「周一~周日 × 第 1-12 节」生成的网格课表，数据来自你本学期的选课记录。
      默认展示当前学期，可切换查看历史学期。
    </p>

    <div class="card">
      <div class="toolbar">
        <el-select v-model="semesterId" placeholder="选择学期" style="width: 240px" @change="load">
          <el-option v-for="s in semesters" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-tag effect="plain">共 {{ tt.course_count || 0 }} 门课程</el-tag>
        <el-tag type="success" effect="plain">合计 {{ tt.total_credits || 0 }} 学分</el-tag>
      </div>

      <table class="timetable">
        <thead>
          <tr>
            <th class="section-col">节次</th>
            <th v-for="d in 7" :key="d">周{{ '一二三四五六日'[d - 1] }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in 12" :key="s">
            <td class="section-col">第 {{ s }} 节</td>
            <td v-for="d in 7" :key="d">
              <div v-for="(c, idx) in tt.grid?.[`${d}-${s}`] || []" :key="idx" class="cell-course"
                   :class="`color-${c.color_key}`">
                <span class="name">{{ c.course_name }}</span>
                <span>{{ c.teacher_name }}</span>
                <span>{{ c.classroom }}</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3 style="font-size: 14px; margin: 0 0 12px; color: #2c3a52">课程明细</h3>
      <el-table :data="tt.courses || []" size="small" border stripe>
        <el-table-column prop="course_code" label="代码" width="110" />
        <el-table-column prop="course_name" label="课程名称" min-width="160" />
        <el-table-column prop="credits" label="学分" width="70" />
        <el-table-column prop="teacher_name" label="教师" width="100" />
        <el-table-column prop="classroom" label="教室" width="130" />
        <el-table-column label="时间" min-width="240">
          <template #default="{ row }">
            <span v-if="!row.time_slots?.length" class="muted">待排</span>
            <span v-else>{{ slotsText(row.time_slots) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { enrollmentApi, semesterApi } from '@/api'

const tt = ref<Record<string, any>>({ grid: {}, courses: [] })
const semesters = ref<any[]>([])
const semesterId = ref<number>()

const slotText = (s: any) => `周${'一二三四五六日'[s.weekday - 1]} 第${s.start_section}-${s.end_section}节`

/**
 * 模板里不要写带类型标注的箭头函数（模板表达式不走 TS 编译，会直接报错），
 * 所有格式化逻辑统一放到 script 里。
 */
const slotsText = (slots: any[]) =>
  (slots || []).map((s) => `${slotText(s)}（${s.weeks_desc || ''}）`).join('；')

async function load() {
  tt.value = (await enrollmentApi.timetable({ semester_id: semesterId.value })) as any
}

onMounted(async () => {
  const list: any = await semesterApi.list()
  semesters.value = list
  const current = list.find((s: any) => s.is_current) || list[0]
  semesterId.value = current?.id
  await load()
})
</script>
