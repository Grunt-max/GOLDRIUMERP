$ErrorActionPreference = "Stop"
$listenPort = 8000
$stopped = @()
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
    if ($isThisErp) {
        Stop-Process -Id $listenerPid -Force
        $stopped += $listenerPid
    }
}

if ($stopped.Count) { Write-Host "Stopped ERP server PID(s): $($stopped -join ', ')" }
else { Write-Host "No ERP server is listening on port 8000." }
