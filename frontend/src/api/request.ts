/**
 * axios 统一封装。
 * 三件事：
 * 1. 请求拦截器自动带上 JWT，前端无需在每个页面手动加 header；
 * 2. 响应拦截器统一解包后端 {code, message, data} 结构，业务代码只拿 data；
 * 3. 错误统一提示 + 401 自动登出跳转，避免每个页面重复写错误处理。
 */
import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

const request: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 20000,
})

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // 统一清洗查询参数：把空串/null/undefined 从 query 里剔除。
  // 原因：筛选表单初始值常是空字符串，而后端的枚举类型查询参数不接受空值，
  // 直传会拿到 422。在这里收口，避免每个页面各自判断。
  if (config.params) {
    const cleaned: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(config.params as Record<string, unknown>)) {
      if (value === '' || value === null || value === undefined) continue
      cleaned[key] = value
    }
    config.params = cleaned
  }
  return config
})

request.interceptors.response.use(
  (response) => {
    const body = response.data
    // 后端统一返回 {code, message, data}
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 'OK') {
        return body.data
      }
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    const message = error.response?.data?.message || error.message || '网络异常'

    if (status === 401) {
      ElMessage.error(message || '登录已失效，请重新登录')
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (!location.hash.includes('/login')) {
        location.hash = '#/login'
      }
    } else if (status === 403) {
      ElMessage.error(message || '没有权限执行该操作')
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default request
