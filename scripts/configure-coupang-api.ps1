$ErrorActionPreference = "Stop"

function Read-PlainSecret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

$accessKey = Read-Host "Coupang Access Key"
$secretKey = Read-PlainSecret "Coupang Secret Key"
$vendorId = Read-Host "Coupang Vendor ID (example: A00012345)"

foreach ($value in @($accessKey, $secretKey, $vendorId)) {
    if ([string]::IsNullOrWhiteSpace($value)) { throw "All three Coupang API values are required." }
    if ($value -match "['`r`n]") { throw "An API value contains an unsupported character." }
}

$target = Join-Path $PSScriptRoot "..\config\marketplace-secrets.ps1"
$lines = if (Test-Path -LiteralPath $target) { @(Get-Content -LiteralPath $target) } else { @() }
$lines = @($lines | Where-Object { $_ -notmatch '^\$env:COUPANG_(ACCESS_KEY|SECRET_KEY|VENDOR_ID)\s*=' })
$lines += "`$env:COUPANG_ACCESS_KEY = '$accessKey'"
$lines += "`$env:COUPANG_SECRET_KEY = '$secretKey'"
$lines += "`$env:COUPANG_VENDOR_ID = '$vendorId'"
Set-Content -LiteralPath $target -Value $lines -Encoding UTF8

Write-Host "Coupang API settings saved without changing the Naver settings."
Write-Host "Restart the ERP server, then use Open Market Management > Coupang > Get Products."
