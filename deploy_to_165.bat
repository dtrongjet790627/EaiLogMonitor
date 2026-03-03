@echo off
chcp 65001 >nul
echo ========================================
echo EAI日志监听服务 - 部署到165服务器
echo ========================================
echo.

REM 目标服务器共享路径 (需要先映射或直接使用UNC路径)
set TARGET_SHARE=\\172.17.10.165\d$\eai_log_monitor
set LOCAL_DIR=%~dp0

echo 源目录: %LOCAL_DIR%
echo 目标目录: %TARGET_SHARE%
echo.

REM 检查是否能访问目标服务器
echo 检查服务器连通性...
ping -n 1 172.17.10.165 >nul 2>&1
if errorlevel 1 (
    echo [错误] 无法连接到172.17.10.165
    echo 请检查网络连接
    pause
    exit /b 1
)
echo [OK] 服务器可达

echo.
echo 尝试访问共享目录...
if not exist "\\172.17.10.165\d$\" (
    echo [警告] 无法访问 \\172.17.10.165\d$
    echo 请确保:
    echo   1. 你有访问权限
    echo   2. 服务器已开启管理共享
    echo.
    echo 你可以尝试先运行:
    echo   net use \\172.17.10.165\d$ /user:administrator [密码]
    echo.
    pause
    exit /b 1
)
echo [OK] 共享目录可访问

REM 创建目标目录
echo.
echo 创建目标目录...
if not exist "%TARGET_SHARE%\" (
    mkdir "%TARGET_SHARE%"
)

REM 复制文件
echo.
echo 复制文件...
echo   - config.py
copy /Y "%LOCAL_DIR%config.py" "%TARGET_SHARE%\"
echo   - log_parser.py
copy /Y "%LOCAL_DIR%log_parser.py" "%TARGET_SHARE%\"
echo   - db_handler.py
copy /Y "%LOCAL_DIR%db_handler.py" "%TARGET_SHARE%\"
echo   - eai_log_monitor.py
copy /Y "%LOCAL_DIR%eai_log_monitor.py" "%TARGET_SHARE%\"
echo   - requirements.txt
copy /Y "%LOCAL_DIR%requirements.txt" "%TARGET_SHARE%\"
echo   - start.bat
copy /Y "%LOCAL_DIR%start_production.bat" "%TARGET_SHARE%\start.bat"
echo   - README.md
copy /Y "%LOCAL_DIR%README.md" "%TARGET_SHARE%\"

echo.
echo ========================================
echo 部署完成！
echo ========================================
echo.
echo 下一步操作:
echo 1. 远程登录到165服务器
echo 2. 进入目录: D:\eai_log_monitor
echo 3. 运行: pip install -r requirements.txt
echo 4. 确保Oracle Instant Client已安装
echo 5. 双击 start.bat 启动服务
echo.
pause
