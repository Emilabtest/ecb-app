# watchdog.ps1 -- Server self-healing monitor (operational, no app code touched).
#
# Polls the server health every 15s. If the server is down, it restarts
# start_dev.bat automatically so the app is ready when needed. If the port
# is bound but unhealthy 6 times in a row (~90s), the stuck holder is
# killed first. Stale projection-feed processes (port 5004) are cleared on
# restart so a fresh broadcast starts clean. The camera sidecar (5002) is
# never touched. All actions are logged to watchdog.log.
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $proj) { $proj = "C:\Users\LIFE HOPE CENTER\Documents\2nd Project" }
$log  = Join-Path $proj "watchdog.log"
$bad  = 0

function Log($msg) {
    Add-Content -LiteralPath $log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg) -ErrorAction SilentlyContinue
}

Log "watchdog started"
while ($true) {
    Start-Sleep -Seconds 15
    $up = $false
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:5010/api/broadcast/status" -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $up = $true }
    } catch { $up = $false }
    if ($up) { $bad = 0; continue }

    $holder = Get-NetTCPConnection -LocalPort 5010 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
    if (-not $holder) {
        Log "DOWN (port free) -> restarting server"
        Get-NetTCPConnection -LocalPort 5004 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
        Start-Process cmd.exe -ArgumentList "/c", ("`"{0}`"" -f (Join-Path $proj "start_dev.bat")) -WindowStyle Hidden -WorkingDirectory $proj
        $bad = 0
    } else {
        $bad += 1
        if ($bad -ge 6) {
            Log "UNHEALTHY (pid $holder, 6x) -> killing holder + restarting"
            Stop-Process -Id $holder -Force -ErrorAction SilentlyContinue
            Get-NetTCPConnection -LocalPort 5004 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 3
            Start-Process cmd.exe -ArgumentList "/c", ("`"{0}`"" -f (Join-Path $proj "start_dev.bat")) -WindowStyle Hidden -WorkingDirectory $proj
            $bad = 0
        }
    }
}
