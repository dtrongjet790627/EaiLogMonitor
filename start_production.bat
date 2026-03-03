@echo off
chcp 65001 >nul
echo ========================================
echo EAI日志监听服务 - 生产环境 (165服务器)
echo ========================================

REM 设置环境变量为生产环境
set EAI_MONITOR_ENV=production

REM 切换到脚本目录
cd /d "%~dp0"

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查Oracle Instant Client
echo 检查Oracle Instant Client...
python -c "import cx_Oracle; print('cx_Oracle版本:', cx_Oracle.version)" 2>nul
if errorlevel 1 (
    echo [警告] cx_Oracle未安装或Oracle Instant Client未配置
    echo.
    echo 请确保:
    echo   1. 已安装Oracle Instant Client
    echo   2. 已将Instant Client目录添加到系统PATH
    echo   3. 已安装cx_Oracle: pip install cx_Oracle
    echo.
)

REM 检查并安装依赖
echo.
echo 检查Python依赖包...
pip show paramiko >nul 2>&1
if errorlevel 1 (
    echo 安装依赖包...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)
echo [OK] 依赖包已就绪

echo.
echo ========================================
echo 启动监听服务 (生产环境)
echo ========================================
echo.
echo 配置信息:
echo   - EAI服务器: 172.17.10.163:2200
echo   - ACC数据库: 172.17.10.165:1521
echo   - 日志级别: INFO
echo.
echo 按 Ctrl+C 停止服务
echo.

python eai_log_monitor.py

REM 如果服务异常退出
echo.
echo [警告] 服务已停止
echo 查看 eai_monitor.log 了解详情
pause
