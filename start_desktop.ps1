# ── AI Serial Bridge 桌面启动器（PowerShell）───────────────────────────
# 固定使用本工程 .venv 内的 Python，避免 PATH 上的系统 Python 缺少依赖。
#
# 用法：
#   .\start_desktop.ps1            # 无控制台窗口启动
#   .\start_desktop.ps1 -Console   # 保留控制台以查看后端日志

[CmdletBinding()]
param(
    [switch]$Console
)

$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectDir '.venv\Scripts\python.exe'
$VenvPythonw = Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'
$DesktopPy = Join-Path $ProjectDir 'desktop.py'
$FrontendIndex = Join-Path $ProjectDir 'frontend\dist\index.html'

if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] 未找到 .venv 虚拟环境：$VenvPython" -ForegroundColor Red
    Write-Host '        请先执行：' -ForegroundColor Yellow
    Write-Host '          py -3.13 -m venv .venv'
    Write-Host '          .venv\Scripts\python.exe -m pip install -r backend\requirements-desktop.txt'
    exit 1
}

if (-not (Test-Path $FrontendIndex)) {
    Write-Host "[ERROR] 未找到前端构建产物：$FrontendIndex" -ForegroundColor Red
    Write-Host '        请先执行：cd frontend; npm ci; npm run build' -ForegroundColor Yellow
    exit 1
}

# 用 venv 的解释器自检，依赖缺失时给出明确提示而不是抛裸 traceback
& $VenvPython -c 'import uvicorn, webview, fastapi' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] .venv 中依赖不完整（缺少 uvicorn/webview/fastapi）" -ForegroundColor Red
    Write-Host '        请执行：.venv\Scripts\python.exe -m pip install -r backend\requirements-desktop.txt' -ForegroundColor Yellow
    exit 1
}

if ($Console) {
    & $VenvPython $DesktopPy
} else {
    Start-Process -FilePath $VenvPythonw -ArgumentList $DesktopPy -WorkingDirectory $ProjectDir
    Write-Host 'AI Serial Bridge 已启动（无控制台窗口）。' -ForegroundColor Green
    Write-Host '如需查看后端日志，请使用：.\start_desktop.ps1 -Console' -ForegroundColor DarkGray
}