<template>
  <div>
    <h2 class="page-title">学业体检</h2>
    <p class="page-desc">
      从「挂科风险、绩点预警、学分进度落后、成绩下滑趋势、毕业风险」五个维度对学业状态打分，
      每条预警都给出触发原因和干预建议，而不是一个孤零零的分数。
    </p>

    <div class="card">
      <div class="head-row">
        <div>
          <div class="muted">综合风险分（0-100，越高越需要关注）</div>
          <div class="big-score" :class="levelClass">{{ risk.risk_score ?? 0 }}</div>
        </div>
        <div class="level-box">
          <el-tag :type="tagType" size="large" effect="dark">
            {{ risk.healthy ? '状态良好' : levelLabel }}
          </el-tag>
          <div class="muted" style="margin-top: 8px">
            {{ risk.student_name }} · {{ risk.student_no }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="risk.healthy" class="card">
      <el-result icon="success" title="未发现学业风险" sub-title="继续保持，记得关注学分进度与先修课安排" />
    </div>

    <div v-for="(f, idx) in risk.findings || []" :key="idx" class="card finding">
      <div class="finding-head">
        <div>
          <el-tag :type="levelTag(f.risk_level)" size="small" effect="dark">{{ levelText(f.risk_level) }}</el-tag>
          <b class="finding-title">{{ f.title }}</b>
        </div>
        <span class="muted">该项评分 {{ f.risk_score }}</span>
      </div>
      <ul class="reason-list">
        <li v-for="(r, i) in f.reasons" :key="i">{{ r }}</li>
      </ul>
      <div class="suggestion">
        <el-icon><Opportunity /></el-icon>
        <span>{{ f.suggestion }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { analysisApi } from '@/api'

const risk = ref<Record<string, any>>({ findings: [], healthy: true })

const levelLabel = computed(() => ({ HIGH: '高风险', MEDIUM: '中风险', LOW: '低风险' } as any)[risk.value.risk_level] || '')
const levelClass = computed(() =>
  risk.value.risk_level === 'HIGH' ? 'danger' : risk.value.risk_level === 'MEDIUM' ? 'warn' : 'ok',
)
const tagType = computed(() =>
  risk.value.risk_level === 'HIGH' ? 'danger' : risk.value.risk_level === 'MEDIUM' ? 'warning' : 'success',
)
const levelTag = (lv: string) => ({ HIGH: 'danger', MEDIUM: 'warning', LOW: 'success' } as any)[lv] || 'info'
const levelText = (lv: string) => ({ HIGH: '高风险', MEDIUM: '中风险', LOW: '低风险' } as any)[lv] || lv

onMounted(async () => {
  risk.value = (await analysisApi.myRisk()) as any
})
</script>

<style scoped>
.head-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}

.big-score {
  font-size: 46px;
  font-weight: 700;
  line-height: 1.1;
}

.big-score.ok {
  color: #12a150;
}

.big-score.warn {
  color: #f59e0b;
}

.big-score.danger {
  color: #e5484d;
}

.level-box {
  text-align: right;
}

.finding-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.finding-title {
  margin-left: 10px;
  font-size: 15px;
}

.suggestion {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-top: 12px;
  padding: 10px 12px;
  background: #f4f8ff;
  border-left: 3px solid #2f6fed;
  border-radius: 4px;
  font-size: 13px;
  color: #35476b;
  line-height: 1.8;
}
</style>
