$ErrorActionPreference = "Stop"
$marketplaceSecrets = Join-Path $PSScriptRoot "..\config\marketplace-secrets.ps1"
if (Test-Path -LiteralPath $marketplaceSecrets) {
    . $marketplaceSecrets
}
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
$secretPath = Join-Path $projectPath ".artifact_work\erp-secret.key"
$listenPort = 8000

# A stopped PowerShell host can leave its Waitress child alive on Windows.
# Remove only processes that both listen on our port and have the exact ERP
# Waitress command signature. This prevents multiple old code versions from
# sharing port 8000 and returning inconsistent pages.
$listenerLines = netstat -ano -p TCP | Select-String ":$listenPort\s+.*LISTENING\s+(\d+)\s*$"
$listenerPids = @(
    foreach ($line in $listenerLines) {
        if ($line.Line -match "LISTENING\s+(\d+)\s*$") { [int]$Matches[1] }
    }
) | Sort-Object -Unique

foreach ($listenerPid in $listenerPids) {
    $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid" -ErrorAction SilentlyContinue
    $commandLine = [string]$candidate.CommandLine
    $isThisErp = $candidate.Name -eq "python.exe" -and
        $commandLine -match "(?i)-m\s+waitress" -and
        $commandLine -match "(?i)127\.0\.0\.1:8000" -and
        $commandLine -match "(?i)config\.wsgi:application"
    if (-not $isThisErp) {
        throw "Port $listenPort is occupied by a non-ERP process (PID $listenerPid). Startup stopped for safety."
    }
    Stop-Process -Id $listenerPid -Force
}

if ($listenerPids.Count -gt 0) {
    $deadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 250
        $stillListening = netstat -ano -p TCP | Select-String ":$listenPort\s+.*LISTENING\s+\d+\s*$"
    } while ($stillListening -and (Get-Date) -lt $deadline)
    if ($stillListening) { throw "Port $listenPort did not clear after stopping old ERP servers." }
}
$tailscaleHost = "desktop-1i805ut.tail587e4a.ts.net"
$env:ERP_ALLOWED_HOSTS = $tailscaleHost
$env:ERP_CSRF_TRUSTED_ORIGINS = "https://$tailscaleHost"
$env:ERP_DEBUG = "0"
if (-not $env:ERP_SECRET_KEY -and (Test-Path $secretPath)) {
    $env:ERP_SECRET_KEY = (Get-Content -LiteralPath $secretPath -Raw).Trim()
}
$userEnvironment = Get-ItemProperty -Path "HKCU:\Environment" -ErrorAction SilentlyContinue

foreach ($name in @("ERP_SECRET_KEY", "ERP_ALLOWED_HOSTS", "ERP_CSRF_TRUSTED_ORIGINS")) {
    if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
        $value = $userEnvironment.$name
        if ($value) { [Environment]::SetEnvironmentVariable($name, $value, "Process") }
    }
}

if (-not $env:ERP_SECRET_KEY) {
    throw "ERP_SECRET_KEY 사용자 환경변수가 없습니다. 운영 설정을 먼저 완료하세요."
}
Set-Location $projectPath
& $pythonPath manage.py migrate --noinput
& $pythonPath manage.py collectstatic --noinput
& $pythonPath -m waitress --listen=127.0.0.1:$listenPort config.wsgi:application
