$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = 'D:\DevTools\venvs\secure-task-manager\Scripts\python.exe'

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --onefile --windowed --name TaskManagerLauncher launcher\task_manager_launcher.py
    Move-Item -LiteralPath (Join-Path $projectRoot 'dist\TaskManagerLauncher.exe') -Destination (Join-Path $projectRoot 'dist\TaskManagerLauncher.next.exe') -Force
}
finally {
    Pop-Location
}
