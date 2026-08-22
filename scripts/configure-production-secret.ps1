$ErrorActionPreference = "Stop"
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$artifactPath = Join-Path $projectPath ".artifact_work"
$secretPath = Join-Path $artifactPath "erp-secret.key"
New-Item -ItemType Directory -Path $artifactPath -Force | Out-Null
$bytes = New-Object byte[] 48
$generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$generator.GetBytes($bytes)
$generator.Dispose()
$secret = [Convert]::ToBase64String($bytes)
[System.IO.File]::WriteAllText($secretPath, $secret, [System.Text.Encoding]::UTF8)
$runtimeIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $secretPath /inheritance:r /grant:r "DESKTOP-1I805UT\USER:(R,W)" "${runtimeIdentity}:(R,W)" | Out-Null
Write-Output "Protected ERP secret configured."
