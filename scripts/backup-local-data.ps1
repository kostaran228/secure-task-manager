$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$docker = 'D:\DevTools\Docker\resources\bin\docker.exe'
$backupDirectory = 'D:\TaskManagerData\backups'
New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupFile = Join-Path $backupDirectory "task-manager-$timestamp.sql"

& $docker compose -f (Join-Path $projectRoot 'docker-compose.yml') exec -T db pg_dump -U task_user tasks | Set-Content -LiteralPath $backupFile -Encoding utf8
Write-Output "Backup created: $backupFile"
