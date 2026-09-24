# Build the Leiturgia Setup EXE.
# Run from the 2nd Project folder:  powershell -File installer\build_installer.ps1
# Optional: -DryDir <path> (default: Temp\opencode\upd144\stage, the signed bundle)
param(
  [string]$DryDir = "C:\Users\LIFEHO~1\AppData\Local\Temp\opencode\upd144\stage"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path   # ...\installer
$root = Split-Path -Parent $here                          # project root
$stage = Join-Path $here "stage"

$version = (Get-Content (Join-Path $root "app.version") -Raw).Trim()
Write-Host "Leiturgia Setup build, version $version"

# --- assemble stage/ ---
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item (Join-Path $DryDir "Leiturgia.exe"), (Join-Path $DryDir "LeiturgiaServer.exe"), `
          (Join-Path $DryDir "config.json"), (Join-Path $DryDir "app.version") $stage -Force
Copy-Item (Join-Path $root "dist\updater.exe") $stage -Force
New-Item -ItemType Directory -Path (Join-Path $stage "data") | Out-Null
Copy-Item (Join-Path $DryDir "data\bible_en.db"), (Join-Path $DryDir "data\bible_tl.db") `
          (Join-Path $stage "data") -Force
Copy-Item (Join-Path $root "templates") (Join-Path $stage "templates") -Recurse -Force
Copy-Item (Join-Path $root "static") (Join-Path $stage "static") -Recurse -Force
if (Test-Path (Join-Path $stage "license.dat")) { Remove-Item (Join-Path $stage "license.dat") -Force }

# --- compile ---
$iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "C:\Program Files\Inno Setup 7\iscc.exe" }
& $iscc "/DMyAppVersion=$version" (Join-Path $here "leiturgia.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed: $LASTEXITCODE" }
Get-ChildItem (Join-Path $here "installer_out\*.exe") | Select-Object Name, Length
