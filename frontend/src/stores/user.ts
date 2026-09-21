/**
 * 用户与权限状态（Pinia）。
 * 菜单与路由守卫都基于这里的 role 判断，做到"前端按角色渲染，后端按角色鉴权"双层控制 ——
 * 前端控制的是体验，后端才是真正的安全边界。
 */
import { defineStore } from 'pinia'
import { authApi } from '@/api'

interface Profile {
  type?: string
  student_no?: string
  name?: string
  major_id?: number
  class_id?: number
  enrollment_year?: number
  title?: string
  college?: string
}

interface UserState {
  token: string
  user: Record<string, any> | null
  profile: Profile | null
}

export const useUserStore = defineStore('user', {
  state: (): UserState => ({
    token: localStorage.getItem('token') || '',
    user: JSON.parse(localStorage.getItem('user') || 'null'),
    profile: JSON.parse(localStorage.getItem('profile') || 'null'),
  }),

  getters: {
    role: (state) => state.user?.role || '',
    isAdmin: (state) => state.user?.role === 'ADMIN',
    isStudent: (state) => state.user?.role === 'STUDENT',
    isTeacher: (state) => state.user?.role === 'TEACHER',
    displayName: (state) => state.profile?.name || state.user?.real_name || '未登录',
  },

  actions: {
    async login(username: string, password: string) {
      const data: any = await authApi.login({ username, password })
      this.token = data.access_token
      this.user = data.user
      this.profile = data.profile
      localStorage.setItem('token', this.token)
      localStorage.setItem('user', JSON.stringify(this.user))
      localStorage.setItem('profile', JSON.stringify(this.profile))
      return data
    },

    async logout() {
      try {
        await authApi.logout()
      } catch {
        // 登出接口失败也要清本地状态，保证用户能正常退出
      }
      this.token = ''
      this.user = null
      this.profile = null
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      localStorage.removeItem('profile')
    },

    async fetchMe() {
      const data: any = await authApi.me()
      this.user = data.user
      this.profile = data.profile
      localStorage.setItem('user', JSON.stringify(this.user))
      localStorage.setItem('profile', JSON.stringify(this.profile))
      return data
    },
  },
})
