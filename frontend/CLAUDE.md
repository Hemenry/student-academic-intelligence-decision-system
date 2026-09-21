# 学生管理系统 · 前端开发约定

## 技术栈
Vue 3 + Vite 5 + TypeScript + Element Plus + Pinia + Vue Router + axios
开发端口 **5174**，通过 Vite proxy 把 `/api` 转发到后端 `127.0.0.1:8008`。

## 硬性约定（踩过坑，务必遵守）

1. **不要在模板表达式里写带类型标注的箭头函数**
   `{{ list.map((s: any) => ...) }}` 会导致组件编译/渲染失败、页面白屏。
   所有格式化逻辑放到 `<script setup>` 里定义函数再调用。

2. **模板里引用的变量必须在 script 中定义**
   例如 `grid[...]` 必须是 `tt.grid[...]`。未定义标识符在模板里不会报编译错，
   而是运行时抛错导致整页白屏，排查成本很高。

3. **查询参数由 axios 请求拦截器统一清洗**（`src/api/request.ts`）
   空字符串/null/undefined 一律不发送，避免后端枚举类型参数返回 422。
   新增筛选表单时直接透传即可，不需要自己过滤。

4. **所有接口调用集中写在 `src/api/index.ts`**，页面不直接写 URL。

5. **角色菜单与路由由 `router/index.ts` 的 `meta.roles` 统一声明**，
   MainLayout 自动按当前角色过滤菜单，新增页面只改 router 一处。

## 页面清单
- 登录：`Login.vue`（带演示账号一键填充）
- 学生端：Home / SelectCourse / Timetable / MyGrades / Recommend / Graduation / MyRisk
- 管理端：Majors / Classes / Courses / Semesters / Offerings / Students / GradeEntry / Alerts / Rules / EnrollStats

## 调试手法
前端白屏时，先用浏览器注入错误监听再复现：
```js
window.__errs=[];window.addEventListener('error',e=>window.__errs.push(e.message));
window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));
```
再用菜单点击做**客户端跳转**（整页 reload 会清掉监听）。
`vite build` 通过不代表运行时没问题，模板表达式错误只有真实渲染才暴露。
