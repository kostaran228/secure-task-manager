$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand -and (Test-Path 'D:\DevTools\Docker\resources\bin\docker.exe')) {
    $dockerCommand = Get-Item 'D:\DevTools\Docker\resources\bin\docker.exe'
}
if (-not $dockerCommand) {
    throw 'Docker Desktop was not found. Start Docker Desktop first, then run this file again.'
}

Set-Location $projectRoot
& $dockerCommand.Source compose up --build --detach
Start-Process 'http://localhost:8000'
