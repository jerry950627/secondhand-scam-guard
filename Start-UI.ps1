$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = Join-Path $Root "server.py"
$PidFile = Join-Path $Root ".server.pid"

# 從 PATH 解析 Python（python 優先，退而求 py 啟動器），不硬編碼特定機器路徑。
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $Python) {
    Write-Error "找不到 Python，請先安裝 Python 3 並加入 PATH（或改用 'py' 啟動器）。"
}

# 1. 先確保 4B LLM（Ollama）有起來，這樣 UI 會自動進入 LLM 模式。
$StartOllama = Join-Path $Root "Start-Ollama.ps1"
if (Test-Path $StartOllama) {
    try { & $StartOllama } catch { Write-Host "（Ollama 未啟動，將以離線規則模式運作）" }
}

# 2. 設定環境變數：自動偵測 LLM、逾時拉長以吸收冷啟動、UTF-8 輸出。
$env:PYTHONUTF8 = "1"
$env:SCAM_LLM_ENABLED = "auto"   # auto＝偵測到 Ollama 就用，否則自動降級規則模式
$env:SCAM_LLM_TIMEOUT = "120"

# 3. 停掉舊的伺服器再啟動新的（先確認該 PID 仍是本服務，避免 PID 重用誤殺）。
if (Test-Path $PidFile) {
    $OldPid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($OldPid) {
        $OldProc = Get-CimInstance Win32_Process -Filter "ProcessId = $OldPid" -ErrorAction SilentlyContinue
        if ($OldProc -and $OldProc.CommandLine -like "*server.py*") {
            Stop-Process -Id $OldPid -ErrorAction SilentlyContinue
        }
    }
}

$Process = Start-Process -FilePath $Python -ArgumentList @($Server) -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $PidFile -Value $Process.Id -Encoding ASCII

# 4. 等伺服器起來並回報 LLM 狀態。
Start-Sleep -Seconds 2
$Mode = "離線規則模式"
try {
    $Health = (Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 5 -UseBasicParsing).Content | ConvertFrom-Json
    if ($Health.llm_available) { $Mode = "4B LLM 模式（gemma3:4b）" }
} catch {}

Start-Process "http://127.0.0.1:8765"

Write-Host "二手交易 AI 防踩雷助理已啟動：http://127.0.0.1:8765"
Write-Host "目前模式：$Mode"
Write-Host "停止服務請執行：.\Stop-UI.ps1"
