/**
 * 接口层：按后端模块分组，页面里只调用这里的方法，不直接写 URL。
 * 好处是接口路径变更时只改一个文件，也便于在类型层面统一约束返回结构。
 */
import request from './request'

export interface Paged<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

type AnyObj = Record<string, any>

// ------------------------------ 认证 ------------------------------
export const authApi = {
  login: (data: { username: string; password: string }) => request.post<any, any>('/auth/login', data),
  logout: () => request.post<any, any>('/auth/logout'),
  me: () => request.get<any, any>('/auth/me'),
  changePassword: (data: { old_password: string; new_password: string }) =>
    request.post<any, any>('/auth/change-password', data),
}

// ------------------------------ 组织 ------------------------------
export const orgApi = {
  majors: () => request.get<any, any>('/majors'),
  createMajor: (data: AnyObj) => request.post<any, any>('/majors', data),
  updateMajor: (id: number, data: AnyObj) => request.put<any, any>(`/majors/${id}`, data),
  deleteMajor: (id: number) => request.delete<any, any>(`/majors/${id}`),

  classes: (params?: AnyObj) => request.get<any, any>('/classes', { params }),
  createClass: (data: AnyObj) => request.post<any, any>('/classes', data),
  updateClass: (id: number, data: AnyObj) => request.put<any, any>(`/classes/${id}`, data),
  deleteClass: (id: number) => request.delete<any, any>(`/classes/${id}`),

  teachers: () => request.get<any, any>('/teachers'),
}

// ------------------------------ 学生 ------------------------------
export const studentApi = {
  list: (params?: AnyObj) => request.get<any, any>('/students', { params }),
  detail: (id: number) => request.get<any, any>(`/students/${id}`),
  create: (data: AnyObj) => request.post<any, any>('/students', data),
  update: (id: number, data: AnyObj) => request.put<any, any>(`/students/${id}`, data),
  remove: (id: number) => request.delete<any, any>(`/students/${id}`),
  resetPassword: (id: number, newPassword = '123456') =>
    request.post<any, any>(`/students/${id}/reset-password`, null, { params: { new_password: newPassword } }),
}

// ------------------------------ 课程 ------------------------------
export const courseApi = {
  list: (params?: AnyObj) => request.get<any, any>('/courses', { params }),
  detail: (id: number) => request.get<any, any>(`/courses/${id}`),
  create: (data: AnyObj) => request.post<any, any>('/courses', data),
  update: (id: number, data: AnyObj) => request.put<any, any>(`/courses/${id}`, data),
  remove: (id: number) => request.delete<any, any>(`/courses/${id}`),
  setPrerequisites: (id: number, data: AnyObj[]) => request.put<any, any>(`/courses/${id}/prerequisites`, data),
}

// ------------------------------ 学期 ------------------------------
export const semesterApi = {
  list: () => request.get<any, any>('/semesters'),
  current: () => request.get<any, any>('/semesters/current'),
  create: (data: AnyObj) => request.post<any, any>('/semesters', data),
  update: (id: number, data: AnyObj) => request.put<any, any>(`/semesters/${id}`, data),
  openSelection: (id: number, params?: AnyObj) =>
    request.post<any, any>(`/semesters/${id}/open-selection`, null, { params }),
  closeSelection: (id: number) => request.post<any, any>(`/semesters/${id}/close-selection`),
}

// ------------------------------ 开课计划 ------------------------------
export const offeringApi = {
  list: (params?: AnyObj) => request.get<any, any>('/offerings', { params }),
  selectable: (params?: AnyObj) => request.get<any, any>('/offerings/selectable', { params }),
  detail: (id: number) => request.get<any, any>(`/offerings/${id}`),
  create: (data: AnyObj) => request.post<any, any>('/offerings', data),
  update: (id: number, data: AnyObj) => request.put<any, any>(`/offerings/${id}`, data),
  remove: (id: number) => request.delete<any, any>(`/offerings/${id}`),
}

// ------------------------------ 选课 ------------------------------
export const enrollmentApi = {
  select: (data: { offering_id: number; idempotent_key?: string }) =>
    request.post<any, any>('/enrollments/select', data),
  drop: (data: { offering_id: number; reason?: string }) => request.post<any, any>('/enrollments/drop', data),
  my: (params?: AnyObj) => request.get<any, any>('/enrollments/my', { params }),
  timetable: (params?: AnyObj) => request.get<any, any>('/enrollments/timetable', { params }),
  precheck: (data: { offering_id: number }) => request.post<any, any>('/enrollments/precheck', data),
  list: (params?: AnyObj) => request.get<any, any>('/enrollments', { params }),
  statsByCourse: (params?: AnyObj) => request.get<any, any>('/enrollments/stats/by-course', { params }),
}

// ------------------------------ 成绩 ------------------------------
export const gradeApi = {
  my: (params?: AnyObj) => request.get<any, any>('/grades/my', { params }),
  myGpa: () => request.get<any, any>('/grades/my/gpa'),
  myFailed: () => request.get<any, any>('/grades/my/failed'),
  record: (data: AnyObj) => request.put<any, any>('/grades/record', data),
  batchRecord: (items: AnyObj[]) => request.put<any, any>('/grades/batch-record', { items }),
  roster: (offeringId: number) => request.get<any, any>(`/grades/offering/${offeringId}/roster`),
  courseStat: (courseId: number, params?: AnyObj) =>
    request.get<any, any>(`/grades/stats/course/${courseId}`, { params }),
  classRank: (classId: number) => request.get<any, any>('/grades/stats/class-rank', { params: { class_id: classId } }),
}

// ------------------------------ 推荐 ------------------------------
export const recommendApi = {
  courses: (params?: AnyObj) => request.get<any, any>('/recommend/courses', { params }),
  explain: (courseId: number) => request.get<any, any>(`/recommend/explain/${courseId}`),
}

// ------------------------------ 学业分析 ------------------------------
export const analysisApi = {
  graduation: () => request.get<any, any>('/analysis/graduation'),
  myRisk: () => request.get<any, any>('/analysis/my-risk'),
  riskScan: (params?: AnyObj) => request.post<any, any>('/analysis/risk-scan', null, { params }),
  alerts: (params?: AnyObj) => request.get<any, any>('/analysis/alerts', { params }),
  handleAlert: (id: number, params?: AnyObj) =>
    request.post<any, any>(`/analysis/alerts/${id}/handle`, null, { params }),
  studentReport: (id: number) => request.get<any, any>(`/analysis/student/${id}/report`),
  dashboard: () => request.get<any, any>('/analysis/dashboard'),
  rules: () => request.get<any, any>('/rules'),
  updateRule: (id: number, data: AnyObj) => request.put<any, any>(`/rules/${id}`, data),
}
