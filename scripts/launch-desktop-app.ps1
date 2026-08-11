$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $projectRoot 'dist'
$current = Join-Path $dist 'TaskManagerLauncher.exe'
$pending = Join-Path $dist 'TaskManagerLauncher.next.exe'

# Windows cannot replace a running EXE. A newly built launcher is staged as
# *.next.exe and becomes active the next time the user launches the app.
if ((Test-Path -LiteralPath $pending) -and -not (Get-Process -Name 'TaskManagerLauncher' -ErrorAction SilentlyContinue)) {
    Move-Item -LiteralPath $pending -Destination $current -Force
}

if (-not (Test-Path -LiteralPath $current)) {
    throw 'Task Manager Launcher was not found. Build the desktop launcher first.'
}

Start-Process -FilePath $current -WorkingDirectory $projectRoot
