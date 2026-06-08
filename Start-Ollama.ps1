$ErrorActionPreference = "Stop"

# 免安裝版 Ollama 與模型都放在 Downloads。
$OllamaDir = "C:\Users\USER\Downloads\ollama"
$OllamaExe = Join-Path $OllamaDir "ollama.exe"

if (-not (Test-Path $OllamaExe)) {
    Write-Error "找不到 $OllamaExe，請確認 Ollama 已解壓到 Downloads\ollama。"
}

$env:OLLAMA_MODELS = Join-Path $OllamaDir "models"
$env:OLLAMA_HOST = "127.0.0.1:11434"

# 若已在執行就不重複啟動。
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 -UseBasicParsing | Out-Null
    Write-Host "Ollama 已在執行：http://127.0.0.1:11434"
} catch {
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Write-Host "Ollama 已啟動：http://127.0.0.1:11434（模型目錄：$($env:OLLAMA_MODELS)）"
}

Write-Host "可用模型："
& $OllamaExe list
