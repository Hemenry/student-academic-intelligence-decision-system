<template>
  <el-container class="layout">
    <el-aside width="228px" class="aside">
      <div class="logo">
        <el-icon size="20"><School /></el-icon>
        <span>学业管理系统</span>
      </div>
      <el-menu :default-active="route.path" router class="menu" background-color="#111c33" text-color="#c3ccdd"
               active-text-color="#ffffff">
        <el-menu-item v-for="item in menus" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="crumbs">{{ route.meta.title || '首页' }}</div>
        <div class="user-area">
          <el-tag :type="roleTagType" effect="light" size="small">{{ roleLabel }}</el-tag>
          <span class="uname">{{ userStore.displayName }}</span>
          <span class="muted" v-if="userStore.profile?.student_no">{{ userStore.profile.student_no }}</span>
          <el-dropdown @command="onCommand">
            <el-icon class="more"><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password">修改密码</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view v-slot="{ Component }">
          <keep-alive :max="6">
            <component :is="Component" :key="route.path" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>

    <el-dialog v-model="pwdVisible" title="修改密码" width="420px">
      <el-form label-width="90px">
        <el-form-item label="原密码">
          <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="请输入原密码" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdLoading" @click="submitPassword">确认修改</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { authApi } from '@/api'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 菜单直接从路由表派生并过滤角色，新增页面只需要改 router 一处
const menus = computed(() => {
  const main = router.getRoutes().find((r) => r.path === '/')
  const children = (main?.children || []) as any[]
  return children
    .filter((c) => {
      const roles = c.meta?.roles as string[] | undefined
      return !roles || roles.length === 0 || roles.includes(userStore.role)
    })
    .map((c) => ({
      path: c.path.startsWith('/') ? c.path : `/${c.path}`,
      title: c.meta?.title,
      icon: c.meta?.icon || 'Menu',
    }))
})

const roleLabel = computed(() => {
  const map: Record<string, string> = { ADMIN: '教务管理员', TEACHER: '教师', STUDENT: '学生' }
  return map[userStore.role] || '访客'
})
const roleTagType = computed(() => (userStore.isAdmin ? 'danger' : userStore.isTeacher ? 'warning' : 'primary'))

const pwdVisible = ref(false)
const pwdLoading = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '' })

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
      .then(async () => {
        await userStore.logout()
        router.push('/login')
        ElMessage.success('已退出登录')
      })
      .catch(() => {})
  } else if (cmd === 'password') {
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdVisible.value = true
  }
}

async function submitPassword() {
  if (!pwdForm.old_password || pwdForm.new_password.length < 6) {
    ElMessage.warning('请填写原密码，新密码至少 6 位')
    return
  }
  pwdLoading.value = true
  try {
    await authApi.changePassword({ ...pwdForm })
    ElMessage.success('密码已修改，请重新登录')
    pwdVisible.value = false
    await userStore.logout()
    router.push('/login')
  } finally {
    pwdLoading.value = false
  }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}

.aside {
  background: #111c33;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 18px;
  color: #fff;
  font-weight: 600;
  font-size: 15px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.menu {
  border-right: none;
  flex: 1;
  overflow-y: auto;
}

.menu :deep(.el-menu-item) {
  height: 46px;
  line-height: 46px;
  margin: 2px 8px;
  border-radius: 8px;
}

.menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, #2f6fed, #4d8bff);
}

.header {
  height: 60px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 22px;
  box-shadow: 0 1px 6px rgba(15, 35, 95, 0.05);
}

.crumbs {
  font-size: 16px;
  font-weight: 600;
}

.user-area {
  display: flex;
  align-items: center;
  gap: 10px;
}

.uname {
  font-size: 14px;
}

.more {
  cursor: pointer;
  color: #7b8798;
}

.main {
  padding: 20px 22px;
  overflow-y: auto;
  background: var(--bg);
}
</style>
