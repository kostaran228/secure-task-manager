$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = 'D:\DevTools\venvs\secure-task-manager\Scripts\python.exe'
$iscc = @(
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    throw 'Inno Setup 6 is required. Install it with: winget install --id JRSoftware.InnoSetup --exact'
}

Push-Location $projectRoot
try {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'installer\staging', 'installer\output'
    & $python -m PyInstaller --noconfirm --clean --onefile --windowed --name TaskManager --distpath installer\staging --workpath build\installer launcher\task_manager_launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'Unable to build the Task Manager executable.' }
    & $iscc 'installer\TaskManager.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the Windows installer.' }
}
finally {
    Pop-Location
}
