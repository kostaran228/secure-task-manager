$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = 'D:\DevTools\venvs\secure-task-manager\Scripts\python.exe'

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --onefile --windowed --name TaskManagerLauncher.next launcher\task_manager_launcher.py
}
finally {
    Pop-Location
}
