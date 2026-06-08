$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root ".server.pid"

if (Test-Path $PidFile) {
    $PidValue = Get-Content $PidFile | Select-Object -First 1
    if ($PidValue) {
        # 先確認該 PID 仍是本服務（CommandLine 含 server.py），避免 PID 重用誤殺其他行程。
        $Proc = Get-CimInstance Win32_Process -Filter "ProcessId = $PidValue" -ErrorAction SilentlyContinue
        if ($Proc -and $Proc.CommandLine -like "*server.py*") {
            Stop-Process -Id $PidValue -Force
            Write-Host "本機 UI 服務已停止。"
        } else {
            Write-Host "PID $PidValue 已非本服務（可能已結束），略過終止。"
        }
    }
    Remove-Item -LiteralPath $PidFile -Force
} else {
    Write-Host "沒有找到正在執行的本機 UI 服務。"
}
