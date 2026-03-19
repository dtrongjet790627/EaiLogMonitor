# EAI日志监听服务 - 部署到165服务器
# 用法: powershell -ExecutionPolicy Bypass -File scripts\deploy.ps1
#
# 部署目标: 172.17.10.165  D:\CustomApps\eai_log_monitor\
# 服务名称: DT.TechTeam_EAI_Log_Monitor

$ErrorActionPreference = "Stop"

$TargetServer = "172.17.10.165"
$TargetPath   = "D:\CustomApps\eai_log_monitor"
$SharePath    = "\\$TargetServer\d`$\CustomApps\eai_log_monitor"
# 脚本在 scripts/ 子目录，父级才是项目根
$SourcePath   = Split-Path -Parent $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " EAI日志监听服务 - 部署到165服务器" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "源目录 : $SourcePath" -ForegroundColor Yellow
Write-Host "目标   : $SharePath"  -ForegroundColor Yellow
Write-Host ""

# [1/5] 测试网络
Write-Host "[1/5] 测试网络..." -ForegroundColor Gray
if (-not (Test-Connection -ComputerName $TargetServer -Count 1 -Quiet)) {
    Write-Host "[ERROR] 无法连接到 $TargetServer" -ForegroundColor Red
    exit 1
}
Write-Host "       服务器可达" -ForegroundColor Green

# [2/5] 建立网络共享
Write-Host "[2/5] 建立网络连接..." -ForegroundColor Gray
net use "\\$TargetServer\d`$" /delete 2>$null
$cred = Get-Credential -Message "输入 $TargetServer 管理员凭据"
if (-not $cred) {
    Write-Host "[ERROR] 未提供凭据" -ForegroundColor Red
    exit 1
}
$result = net use "\\$TargetServer\d`$" /user:$($cred.UserName) $($cred.GetNetworkCredential().Password) 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] 连接失败: $result" -ForegroundColor Red
    exit 1
}
Write-Host "       连接成功" -ForegroundColor Green

# [3/5] 停止服务
Write-Host "[3/5] 停止服务 DT.TechTeam_EAI_Log_Monitor ..." -ForegroundColor Gray
$stopResult = Invoke-Command -ComputerName $TargetServer -Credential $cred -ScriptBlock {
    sc.exe stop "DT.TechTeam_EAI_Log_Monitor"
    Start-Sleep -Seconds 3
    sc.exe query "DT.TechTeam_EAI_Log_Monitor" | Select-String "STATE"
}
Write-Host "       $stopResult" -ForegroundColor Gray

# [4/5] 复制核心文件（仅服务运行所需文件，不复制工具和脚本）
Write-Host "[4/5] 复制核心文件..." -ForegroundColor Gray
$coreFiles = @(
    "config.py",
    "log_parser.py",
    "db_handler.py",
    "eai_log_monitor.py",
    "backfill_fixed.py",
    "requirements.txt"
)
foreach ($f in $coreFiles) {
    $src = Join-Path $SourcePath $f
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $SharePath -Force
        Write-Host "       [OK] $f" -ForegroundColor Green
    } else {
        Write-Host "       [SKIP] $f 不存在" -ForegroundColor Yellow
    }
}

# [5/5] 启动服务
Write-Host "[5/5] 启动服务..." -ForegroundColor Gray
$startResult = Invoke-Command -ComputerName $TargetServer -Credential $cred -ScriptBlock {
    sc.exe start "DT.TechTeam_EAI_Log_Monitor"
    Start-Sleep -Seconds 3
    sc.exe query "DT.TechTeam_EAI_Log_Monitor" | Select-String "STATE"
}
Write-Host "       $startResult" -ForegroundColor Gray

# 断开共享
net use "\\$TargetServer\d`$" /delete 2>$null

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 部署完成" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "验证日志: ssh Administrator@$TargetServer 后查看 $TargetPath\eai_monitor.log"
