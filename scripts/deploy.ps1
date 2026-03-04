# EAI日志监听服务 - 快速部署脚本
# 用法: powershell -ExecutionPolicy Bypass -File quick_deploy.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "EAI日志监听服务 - 部署到165服务器" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 配置
$TargetServer = "172.17.10.165"
$TargetPath = "D:\eai_log_monitor"
$SourcePath = $PSScriptRoot
$SharePath = "\\$TargetServer\d`$\eai_log_monitor"

Write-Host "源目录: $SourcePath" -ForegroundColor Yellow
Write-Host "目标: $SharePath" -ForegroundColor Yellow
Write-Host ""

# 测试网络连通性
Write-Host "测试网络连通性..." -ForegroundColor Gray
if (-not (Test-Connection -ComputerName $TargetServer -Count 1 -Quiet)) {
    Write-Host "[错误] 无法连接到 $TargetServer" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] 服务器可达" -ForegroundColor Green

# 提示输入凭据
Write-Host ""
Write-Host "请输入165服务器管理员凭据:" -ForegroundColor Yellow
$credential = Get-Credential -Message "请输入 $TargetServer 的管理员用户名和密码"

if (-not $credential) {
    Write-Host "[错误] 未提供凭据" -ForegroundColor Red
    exit 1
}

# 建立网络连接
Write-Host ""
Write-Host "建立网络连接..." -ForegroundColor Gray
try {
    # 先断开已有连接
    net use "\\$TargetServer\d`$" /delete 2>$null

    # 建立新连接
    $result = net use "\\$TargetServer\d`$" /user:$($credential.UserName) $($credential.GetNetworkCredential().Password) 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "连接失败: $result"
    }
    Write-Host "[OK] 网络连接已建立" -ForegroundColor Green
} catch {
    Write-Host "[错误] 无法连接到共享: $_" -ForegroundColor Red
    exit 1
}

# 创建目标目录
Write-Host ""
Write-Host "创建目标目录..." -ForegroundColor Gray
try {
    if (-not (Test-Path $SharePath)) {
        New-Item -Path $SharePath -ItemType Directory -Force | Out-Null
    }
    Write-Host "[OK] 目录已创建: $SharePath" -ForegroundColor Green
} catch {
    Write-Host "[错误] 无法创建目录: $_" -ForegroundColor Red
    exit 1
}

# 复制文件
Write-Host ""
Write-Host "复制文件..." -ForegroundColor Gray

$filesToCopy = @(
    "config.py",
    "log_parser.py",
    "db_handler.py",
    "eai_log_monitor.py",
    "requirements.txt",
    "test_connections.py",
    "README.md",
    "install_service.bat"
)

foreach ($file in $filesToCopy) {
    $sourcefile = Join-Path $SourcePath $file
    if (Test-Path $sourcefile) {
        Copy-Item -Path $sourcefile -Destination $SharePath -Force
        Write-Host "  [OK] $file" -ForegroundColor Green
    } else {
        Write-Host "  [跳过] $file (文件不存在)" -ForegroundColor Yellow
    }
}

# 复制生产启动脚本
$prodBat = Join-Path $SourcePath "start_production.bat"
if (Test-Path $prodBat) {
    Copy-Item -Path $prodBat -Destination (Join-Path $SharePath "start.bat") -Force
    Write-Host "  [OK] start.bat (from start_production.bat)" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "文件复制完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步操作:" -ForegroundColor Yellow
Write-Host "1. 远程登录到165服务器 (mstsc /v:$TargetServer)" -ForegroundColor White
Write-Host "2. 打开命令提示符，进入目录: $TargetPath" -ForegroundColor White
Write-Host "3. 安装依赖: pip install -r requirements.txt" -ForegroundColor White
Write-Host "4. 测试连接: python test_connections.py" -ForegroundColor White
Write-Host "5. 启动服务: start.bat" -ForegroundColor White
Write-Host ""
Write-Host "可选：注册为Windows服务" -ForegroundColor Yellow
Write-Host "   运行: install_service.bat (需要下载nssm.exe)" -ForegroundColor White
Write-Host ""

# 询问是否打开远程桌面
$openRDP = Read-Host "是否打开远程桌面连接? (y/n)"
if ($openRDP -eq "y" -or $openRDP -eq "Y") {
    mstsc /v:$TargetServer
}

Write-Host ""
Write-Host "部署脚本执行完毕。" -ForegroundColor Cyan
