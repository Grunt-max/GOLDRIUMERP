$ErrorActionPreference = "Stop"
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backupRoot = Join-Path $projectPath "backups\automatic"
$resolvedBackupRoot = [System.IO.Path]::GetFullPath($backupRoot)
$expectedParent = [System.IO.Path]::GetFullPath((Join-Path $projectPath "backups"))
if (-not $resolvedBackupRoot.StartsWith($expectedParent + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "안전하지 않은 백업 경로입니다: $resolvedBackupRoot"
}
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path $backupRoot $stamp
New-Item -ItemType Directory -Path $backupPath -Force | Out-Null

$sourceDb = Join-Path $projectPath "db.sqlite3"
$targetDb = Join-Path $backupPath "db.sqlite3"
$pythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
& $pythonPath -c "import sqlite3; src=sqlite3.connect(r'$sourceDb'); dst=sqlite3.connect(r'$targetDb'); src.backup(dst); dst.close(); src.close()"

$mediaPath = Join-Path $projectPath "media"
if (Test-Path $mediaPath) {
    Copy-Item -LiteralPath $mediaPath -Destination (Join-Path $backupPath "media") -Recurse -Force
}

Get-ChildItem -LiteralPath $resolvedBackupRoot -Directory | Sort-Object CreationTime -Descending | Select-Object -Skip 30 | Remove-Item -Recurse -Force
Write-Output "ERP backup completed: $backupPath"
