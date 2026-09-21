/**
 * 路由表 + 权限守卫。
 * meta.roles 声明该页面允许的角色，全局前置守卫统一拦截，
 * 避免把权限判断散落在每个页面里（也防止漏判导致的越权跳转）。
 */
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue'), meta: { public: true, title: '登录' } },
  {
    path: '/',
    component: () => import('@/layout/MainLayout.vue'),
    redirect: '/home',
    children: [
      // ---------------- 学生 ----------------
      {
        path: 'home',
        name: 'home',
        component: () => import('@/views/common/Home.vue'),
        meta: { title: '首页', icon: 'HomeFilled', roles: ['STUDENT', 'ADMIN', 'TEACHER'] },
      },
      {
        path: 'select-course',
        name: 'select-course',
        component: () => import('@/views/student/SelectCourse.vue'),
        meta: { title: '智能选课', icon: 'Search', roles: ['STUDENT'] },
      },
      {
        path: 'timetable',
        name: 'timetable',
        component: () => import('@/views/student/Timetable.vue'),
        meta: { title: '我的课表', icon: 'Calendar', roles: ['STUDENT'] },
      },
      {
        path: 'my-grades',
        name: 'my-grades',
        component: () => import('@/views/student/MyGrades.vue'),
        meta: { title: '我的成绩', icon: 'Trophy', roles: ['STUDENT'] },
      },
      {
        path: 'recommend',
        name: 'recommend',
        component: () => import('@/views/student/Recommend.vue'),
        meta: { title: '智能推荐', icon: 'MagicStick', roles: ['STUDENT'] },
      },
      {
        path: 'graduation',
        name: 'graduation',
        component: () => import('@/views/student/Graduation.vue'),
        meta: { title: '毕业进度', icon: 'Medal', roles: ['STUDENT'] },
      },
      {
        path: 'my-risk',
        name: 'my-risk',
        component: () => import('@/views/student/MyRisk.vue'),
        meta: { title: '学业体检', icon: 'FirstAidKit', roles: ['STUDENT'] },
      },

      // ---------------- 管理端 ----------------
      {
        path: 'majors',
        name: 'majors',
        component: () => import('@/views/admin/Majors.vue'),
        meta: { title: '专业管理', icon: 'School', roles: ['ADMIN'] },
      },
      {
        path: 'classes',
        name: 'classes',
        component: () => import('@/views/admin/Classes.vue'),
        meta: { title: '班级管理', icon: 'UserFilled', roles: ['ADMIN'] },
      },
      {
        path: 'courses',
        name: 'courses',
        component: () => import('@/views/admin/Courses.vue'),
        meta: { title: '课程库', icon: 'Notebook', roles: ['ADMIN'] },
      },
      {
        path: 'semesters',
        name: 'semesters',
        component: () => import('@/views/admin/Semesters.vue'),
        meta: { title: '学期管理', icon: 'Clock', roles: ['ADMIN'] },
      },
      {
        path: 'offerings',
        name: 'offerings',
        component: () => import('@/views/admin/Offerings.vue'),
        meta: { title: '开课计划', icon: 'Grid', roles: ['ADMIN'] },
      },
      {
        path: 'students',
        name: 'students',
        component: () => import('@/views/admin/Students.vue'),
        meta: { title: '学生管理', icon: 'Avatar', roles: ['ADMIN'] },
      },
      {
        path: 'grade-entry',
        name: 'grade-entry',
        component: () => import('@/views/admin/GradeEntry.vue'),
        meta: { title: '成绩录入', icon: 'EditPen', roles: ['ADMIN', 'TEACHER'] },
      },
      {
        path: 'alerts',
        name: 'alerts',
        component: () => import('@/views/admin/Alerts.vue'),
        meta: { title: '学业预警', icon: 'Warning', roles: ['ADMIN', 'TEACHER'] },
      },
      {
        path: 'rules',
        name: 'rules',
        component: () => import('@/views/admin/Rules.vue'),
        meta: { title: '选课规则', icon: 'SetUp', roles: ['ADMIN'] },
      },
      {
        path: 'enroll-stats',
        name: 'enroll-stats',
        component: () => import('@/views/admin/EnrollStats.vue'),
        meta: { title: '选课统计', icon: 'PieChart', roles: ['ADMIN', 'TEACHER'] },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/home' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  const user = JSON.parse(localStorage.getItem('user') || 'null')

  if (to.meta.public) {
    next()
    return
  }
  if (!token) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }
  const roles = to.meta.roles as string[] | undefined
  if (roles && roles.length && !roles.includes(user?.role)) {
    ElMessage.warning('没有访问该页面的权限')
    next({ path: '/home' })
    return
  }
  next()
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 学业管理系统` : '学业过程管理与智能决策系统'
})

export default router
