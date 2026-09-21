<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <el-icon size="30" color="#2f6fed"><School /></el-icon>
        <h1>学业过程管理与智能决策系统</h1>
        <p>教务管理 · 智能选课 · 成绩分析 · 学业预警</p>
      </div>

      <el-form :model="form" @submit.prevent="onSubmit" size="large">
        <el-form-item>
          <el-input v-model="form.username" placeholder="学号 / 工号 / 管理员账号" clearable>
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" show-password
                    @keyup.enter="onSubmit">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>

      <div class="quick">
        <span class="muted">演示账号（密码统一 123456）：</span>
        <div class="chips">
          <el-tag v-for="acct in accounts" :key="acct.username" class="chip" effect="plain"
                  @click="fill(acct.username)" style="cursor: pointer">
            {{ acct.label }}
          </el-tag>
        </div>
      </div>
    </div>
    <div class="footer muted">FastAPI + SQLAlchemy + MySQL + Redis ｜ Vue3 + Vite + TypeScript + Element Plus</div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const loading = ref(false)
const form = reactive({ username: '', password: '' })

const accounts = [
  { label: '管理员 admin', username: 'admin' },
  { label: '学生 24CS101', username: '24CS101' },
  { label: '学生 25SE203', username: '25SE203' },
  { label: '学生 26DS105（新生，无历史成绩）', username: '26DS105' },
  { label: '教师 T1001', username: 'T1001' },
]

function fill(username: string) {
  form.username = username
  form.password = '123456'
}

async function onSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    const data: any = await userStore.login(form.username, form.password)
    ElMessage.success(`欢迎回来，${data.user.real_name}`)
    const redirect = (route.query.redirect as string) || '/home'
    router.push(redirect)
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1d3b8b 0%, #2f6fed 45%, #61a3ff 100%);
}

.login-card {
  width: 420px;
  background: #fff;
  border-radius: 14px;
  padding: 34px 34px 24px;
  box-shadow: 0 18px 50px rgba(9, 27, 76, 0.28);
}

.brand {
  text-align: center;
  margin-bottom: 24px;
}

.brand h1 {
  font-size: 19px;
  margin: 10px 0 6px;
  color: #1f2d3d;
}

.brand p {
  font-size: 12px;
  color: #7b8798;
  margin: 0;
}

.quick {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed #e8ecf3;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.chip:hover {
  color: #2f6fed;
  border-color: #2f6fed;
}

.footer {
  margin-top: 18px;
  color: rgba(255, 255, 255, 0.75);
}
</style>
