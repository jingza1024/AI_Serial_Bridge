# 本地复现 CI 的打包冒烟流程（与 .github/workflows/ci.yml 的 desktop-package job 等价）
$ErrorActionPreference = 'Stop'

$exe = "dist\AI Serial Bridge\AI Serial Bridge.exe"
$index = "dist\AI Serial Bridge\_internal\frontend\dist\index.html"

if (-not (Test-Path $exe)) { throw "缺失可执行文件: $exe" }
if (-not (Test-Path $index)) { throw "前端产物未被打包到 _internal: $index" }
Write-Host "[OK] frozen 布局正确"

$stateDir = Join-Path $env:TEMP "asb-smoke-state"
Remove-Item $stateDir -Recurse -Force -ErrorAction SilentlyContinue
$env:AI_SERIAL_STATE_DIR = $stateDir
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$proc = Start-Process -FilePath $exe -PassThru
Write-Host "已启动 PID $($proc.Id)"

$runtime = Join-Path $stateDir "runtime.json"
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline -and -not (Test-Path $runtime)) {
  Start-Sleep -Milliseconds 500
}
if (-not (Test-Path $runtime)) { throw "超时：未生成 runtime.json（后端未就绪）" }

$manifest = Get-Content $runtime -Raw | ConvertFrom-Json
$base = $manifest.api_url
Write-Host "后端地址: $base"

$response = Invoke-WebRequest "$base/" -UseBasicParsing -TimeoutSec 20
if ($response.StatusCode -ne 200) { throw "GET / 返回 $($response.StatusCode)" }
if ($response.Content -notmatch '<title>AI Serial Bridge</title>') {
  throw "GET / 未返回前端页面，实际内容: $($response.Content.Substring(0, [Math]::Min(200, $response.Content.Length)))"
}
Write-Host "[OK] GET / 返回前端页面"

$asset = [regex]::Match($response.Content, 'src="(\./assets/[^"]+\.js)"').Groups[1].Value
if ($asset) {
  $assetUrl = "$base/" + ($asset -replace '^\./', '')
  $assetResponse = Invoke-WebRequest $assetUrl -UseBasicParsing -TimeoutSec 20
  if ($assetResponse.StatusCode -ne 200) { throw "静态资源 $asset 返回 $($assetResponse.StatusCode)" }
  Write-Host "[OK] 静态资源可访问: $asset ($($assetResponse.RawContentLength) bytes)"
}

$apiConfig = Invoke-WebRequest "$base/api/config" -UseBasicParsing -TimeoutSec 20
if ($apiConfig.StatusCode -ne 200) { throw "/api/config 返回 $($apiConfig.StatusCode)" }
Write-Host "[OK] /api/config 未被静态挂载遮蔽"

$crash = Join-Path $stateDir "logs\crash.log"
if (Test-Path $crash) {
  Write-Host "---- crash.log ----"
  Get-Content $crash
  throw "存在 crash.log，说明启动期发生未捕获异常"
}
Write-Host "[OK] 无 crash.log"

$desktopLog = Join-Path $stateDir "logs\desktop.log"
if (Test-Path $desktopLog) {
  Write-Host "[OK] desktop.log 已写入:"
  Get-Content $desktopLog | Select-Object -Last 5 | ForEach-Object { "      $_" }
}

Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
Write-Host "`n打包冒烟测试通过"
