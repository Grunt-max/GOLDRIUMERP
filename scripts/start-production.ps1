$ErrorActionPreference = "Stop"
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
$secretPath = Join-Path $projectPath ".artifact_work\erp-secret.key"
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
& $pythonPath -m waitress --listen=127.0.0.1:8000 config.wsgi:application
