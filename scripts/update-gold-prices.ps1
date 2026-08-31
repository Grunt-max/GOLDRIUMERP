$ErrorActionPreference = "Stop"
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
$logPath = Join-Path $projectPath ".artifact_work\gold-price-collection.log"
$env:ERP_DEBUG = "1"
Set-Location $projectPath
& $pythonPath manage.py collect_gold_prices *>> $logPath
