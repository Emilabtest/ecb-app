# setup_audio.ps1 -- One-time audio setup for this PC (run via setup_autostart.bat).
#
# Enables all "Stereo Mix" capture endpoints so the app can capture PC output
# sound (video audio, etc.) with ZERO manual Sound-panel steps. Self-elevates
# (UAC prompt once); portable -- no hardcoded paths.
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs -Wait
    exit $LASTEXITCODE
}

$base = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
$count = 0
Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {
    $kp = $base + "\" + $_.PSChildName
    try {
        $props = Get-ItemProperty ($kp + "\Properties") -ErrorAction Stop
        $nm = ($props.PSObject.Properties.Value -join "|")
        if ($nm -match "Stereo Mix") {
            $cur = (Get-ItemProperty -LiteralPath $kp -Name DeviceState -ErrorAction Stop).DeviceState
            $new = ($cur -band (-bnot 15)) -bor 1
            if ($new -ne $cur) {
                Set-ItemProperty -LiteralPath $kp -Name DeviceState -Value ([int]$new) -ErrorAction Stop
            }
            $count++
        }
    } catch { }
}
# Re-enumerate audio endpoints so ffmpeg/dshow sees the change.
try { Restart-Service -Name Audiosrv -Force -ErrorAction Stop } catch { }
"setup_audio: Stereo Mix endpoints found+enabled: $count"
