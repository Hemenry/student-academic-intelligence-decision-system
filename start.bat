@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
rem ============================================================
rem  一键启动：后端 8008 + 前端 5174
rem  用法：双击本文件，或在项目根目录执行 start.bat
rem ============================================================

set "ROOT=%~dp0"
set "BACKEND_PORT=8008"
set "FRONTEND_PORT=5174"

rem ---------- 查找 Python ----------
set "PY="
if defined PYTHON if exist "%PYTHON%" set "PY=%PYTHON%"
if not defined PY if exist "%ROOT%backend\.venv\Scripts\python.exe" set "PY=%ROOT%backend\.venv\Scripts\python.exe"
if not defined PY if exist "C:\Users\win11\.workbuddy\binaries\python\envs\sstudent\Scripts\python.exe" set "PY=C:\Users\win11\.workbuddy\binaries\python\envs\sstudent\Scripts\python.exe"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [X] 找不到可用的 Python，请设置环境变量 PYTHON 指向解释器
  pause & exit /b 1
)

rem ---------- 查找 Node ----------
set "NODE="
where node >nul 2>&1 && set "NODE=node"
if not defined NODE if exist "C:\Users\win11\.workbuddy\binaries\node\versions\22.22.2\node.exe" set "NODE=C:\Users\win11\.workbuddy\binaries\node\versions\22.22.2\node.exe"
if not defined NODE (
  echo [X] 找不到可用的 Node.js，请安装 Node 18+ 并加入 PATH
  pause & exit /b 1
)

echo Python : %PY%
echo Node   : %NODE%
echo.

rem ---------- 后端 ----------
netstat -ano | findstr ":%BACKEND_PORT% " | findstr LISTENING >nul 2>&1
if %errorlevel%==0 (
  echo [*] 后端已在 %BACKEND_PORT% 运行，跳过启动
) else (
  echo [*] 启动后端 http://127.0.0.1:%BACKEND_PORT%
  start "student-system-backend" cmd /k "cd /d "%ROOT%backend" && "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
)

rem ---------- 前端 ----------
netstat -ano | findstr ":%FRONTEND_PORT% " | findstr LISTENING >nul 2>&1
if %errorlevel%==0 (
  echo [*] 前端已在 %FRONTEND_PORT% 运行，跳过启动
) else (
  if not exist "%ROOT%frontend\node_modules" (
    echo [*] 首次运行，安装前端依赖...
    pushd "%ROOT%frontend" && call npm install && popd
  )
  echo [*] 启动前端 http://127.0.0.1:%FRONTEND_PORT%
  start "student-system-frontend" cmd /k "cd /d "%ROOT%frontend" && "%NODE%" node_modules\vite\bin\vite.js --port %FRONTEND_PORT% --host 127.0.0.1"
)

echo.
echo ================= 启动完成 =================
echo 前端页面 : http://127.0.0.1:%FRONTEND_PORT%
echo 接口文档 : http://127.0.0.1:%BACKEND_PORT%/docs
echo 健康检查 : http://127.0.0.1:%BACKEND_PORT%/health
echo.
echo 演示账号（密码统一 123456）：admin / T1001 / 24CS101 / 25SE203 / 26DS105
echo 两个服务分别在新窗口中运行，关闭窗口即停止服务。
echo ============================================
echo.
pause
