<template>
  <div>
    <h2 class="page-title">智能推荐</h2>
    <p class="page-desc">
      推荐结果 = 协同过滤（Item-CF + User-CF 加权）× 55% + 规则因子（毕业缺口 / 专业匹配 / 时间可行性 / 热度）× 45%。
      所有候选课都已通过规则引擎过滤，推给你的课一定选得上。
    </p>

    <div class="card">
      <div class="toolbar">
        <span class="muted">协同过滤权重</span>
        <el-slider v-model="cfWeight" :min="0" :max="1" :step="0.05" style="width: 220px" show-input
                   :show-input-controls="false" />
        <el-select v-model="limit" style="width: 120px" @change="load">
          <el-option :value="5" label="Top 5" />
          <el-option :value="10" label="Top 10" />
          <el-option :value="20" label="Top 20" />
        </el-select>
        <el-button type="primary" @click="load">重新计算推荐</el-button>
        <div style="flex: 1"></div>
        <span class="muted">权重=0 为纯规则推荐，权重=1 为纯协同过滤（可观察冷启动差异）</span>
      </div>

      <div v-loading="loading" class="rec-grid">
        <div v-for="item in list" :key="item.offering_id" class="rec-card">
          <div class="rec-head">
            <div>
              <div class="rec-name">{{ item.course_name }}</div>
              <div class="muted">{{ item.course_code }} · {{ item.credits }} 学分 · {{ typeLabel(item.course_type) }}</div>
            </div>
            <div class="score-badge">
              <div class="score-num">{{ item.score }}</div>
              <div class="score-label">推荐分</div>
            </div>
          </div>

          <div class="metrics">
            <el-tag size="small" effect="plain">协同过滤 {{ item.cf_score }}</el-tag>
            <el-tag size="small" effect="plain" type="success">规则因子 {{ item.rule_score }}</el-tag>
            <el-tag size="small" effect="plain" :type="item.remaining <= 5 ? 'danger' : 'info'">
              余量 {{ item.remaining }}
            </el-tag>
          </div>

          <ul class="reason-list">
            <li v-for="(r, i) in item.reason" :key="i">{{ r }}</li>
          </ul>

          <div class="rec-foot">
            <span class="muted">
              {{ item.teacher_name || '教师待定' }}
              <template v-if="item.time_slots?.length">
                · {{ item.time_slots.map(slotText).join(' / ') }}
              </template>
            </span>
            <el-button type="primary" size="small" @click="doSelect(item)">立即选课</el-button>
          </div>
        </div>

        <el-empty v-if="!loading && list.length === 0"
                  description="暂无可推荐课程（可能本学期可选课程都已修读，或存在硬性条件未满足）" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { enrollmentApi, recommendApi } from '@/api'

const list = ref<any[]>([])
const loading = ref(false)
const cfWeight = ref(0.55)
const limit = ref(10)

const typeLabel = (t: string) =>
  ({ REQUIRED: '专业必修', ELECTIVE: '专业选修', PUBLIC: '公共必修', GENERAL: '通识选修' } as any)[t] || t
const slotText = (s: any) => `周${'一二三四五六日'[s.weekday - 1]}第${s.start_section}-${s.end_section}节`

async function load() {
  loading.value = true
  try {
    list.value = (await recommendApi.courses({ limit: limit.value, cf_weight: cfWeight.value })) as any
  } finally {
    loading.value = false
  }
}

async function doSelect(item: any) {
  try {
    await enrollmentApi.select({
      offering_id: item.offering_id,
      idempotent_key: `${item.offering_id}-${Date.now()}`,
    })
    ElMessage.success(`选课成功：${item.course_name}`)
    load()
  } catch {
    // 统一错误提示
  }
}

onMounted(load)
</script>

<style scoped>
.rec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
  min-height: 160px;
}

.rec-card {
  border: 1px solid #e8ecf3;
  border-radius: 10px;
  padding: 14px 16px;
  background: #fff;
  transition: box-shadow 0.2s, transform 0.2s;
}

.rec-card:hover {
  box-shadow: 0 6px 20px rgba(47, 111, 237, 0.12);
  transform: translateY(-2px);
}

.rec-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.rec-name {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 3px;
}

.score-badge {
  text-align: center;
  background: linear-gradient(135deg, #2f6fed, #61a3ff);
  color: #fff;
  border-radius: 8px;
  padding: 6px 10px;
  min-width: 66px;
}

.score-num {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
}

.score-label {
  font-size: 11px;
  opacity: 0.85;
}

.metrics {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 10px 0 8px;
}

.rec-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #eef1f6;
}
</style>
