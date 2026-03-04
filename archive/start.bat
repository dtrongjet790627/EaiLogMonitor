@echo off
chcp 65001 >nul
echo ========================================
echo EAI日志监听服务 - 本地测试启动
echo ========================================

REM 设置环境变量
set EAI_MONITOR_ENV=local

REM 切换到脚本目录
cd /d "%~dp0"

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

REM 检查依赖
echo 检查依赖包...
pip show paramiko >nul 2>&1
if errorlevel 1 (
    echo 安装依赖包...
    pip install -r requirements.txt
)

echo.
echo 启动监听服务...
echo 按 Ctrl+C 停止服务
echo.

python eai_log_monitor.py

pause
