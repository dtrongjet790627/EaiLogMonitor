@echo off
chcp 65001 >nul
echo ========================================
echo EAI日志监听服务 - Windows服务安装
echo ========================================
echo.

REM 需要管理员权限
net session >nul 2>&1
if errorlevel 1 (
    echo [错误] 请以管理员身份运行此脚本
    pause
    exit /b 1
)

set SERVICE_NAME=EAILogMonitor
set INSTALL_DIR=%~dp0
set PYTHON_PATH=python

echo 服务名称: %SERVICE_NAME%
echo 安装目录: %INSTALL_DIR%
echo.

REM 检查NSSM是否存在
where nssm >nul 2>&1
if errorlevel 1 (
    echo [提示] 需要NSSM (Non-Sucking Service Manager) 来创建Windows服务
    echo 下载地址: https://nssm.cc/download
    echo.
    echo 请下载NSSM并将nssm.exe放到系统PATH中
    echo 或者直接放到本目录
    echo.

    if exist "%INSTALL_DIR%nssm.exe" (
        set NSSM_PATH=%INSTALL_DIR%nssm.exe
        echo [OK] 找到本地nssm.exe
    ) else (
        echo [错误] 未找到nssm.exe
        pause
        exit /b 1
    )
) else (
    set NSSM_PATH=nssm
)

echo.
echo 安装服务...

REM 先尝试移除旧服务
%NSSM_PATH% stop %SERVICE_NAME% >nul 2>&1
%NSSM_PATH% remove %SERVICE_NAME% confirm >nul 2>&1

REM 创建批处理启动脚本
echo @echo off > "%INSTALL_DIR%run_service.bat"
echo set EAI_MONITOR_ENV=production >> "%INSTALL_DIR%run_service.bat"
echo cd /d "%INSTALL_DIR%" >> "%INSTALL_DIR%run_service.bat"
echo python eai_log_monitor.py >> "%INSTALL_DIR%run_service.bat"

REM 安装服务
%NSSM_PATH% install %SERVICE_NAME% "%INSTALL_DIR%run_service.bat"
%NSSM_PATH% set %SERVICE_NAME% AppDirectory "%INSTALL_DIR%"
%NSSM_PATH% set %SERVICE_NAME% DisplayName "EAI日志监听服务"
%NSSM_PATH% set %SERVICE_NAME% Description "监听EAI日志并同步MES报工数据到ACC数据库"
%NSSM_PATH% set %SERVICE_NAME% Start SERVICE_AUTO_START
%NSSM_PATH% set %SERVICE_NAME% AppStdout "%INSTALL_DIR%service_stdout.log"
%NSSM_PATH% set %SERVICE_NAME% AppStderr "%INSTALL_DIR%service_stderr.log"

echo.
echo [OK] 服务安装完成
echo.
echo 启动服务...
%NSSM_PATH% start %SERVICE_NAME%

echo.
echo ========================================
echo 服务管理命令:
echo ========================================
echo   启动: nssm start %SERVICE_NAME%
echo   停止: nssm stop %SERVICE_NAME%
echo   重启: nssm restart %SERVICE_NAME%
echo   状态: nssm status %SERVICE_NAME%
echo   卸载: nssm remove %SERVICE_NAME% confirm
echo.
echo 或使用Windows服务管理:
echo   services.msc
echo.
pause
