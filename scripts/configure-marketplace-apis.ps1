$ErrorActionPreference = "Stop"

function Read-PlainSecret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

$naverClientId = Read-Host "Naver Commerce API Application ID"
$naverSecret = Read-PlainSecret "Naver Application Secret"
$coupangAccessKey = Read-Host "Coupang Access Key (press Enter to skip)"
$coupangSecretKey = Read-PlainSecret "Coupang Secret Key (press Enter to skip)"
$coupangVendorId = Read-Host "Coupang Vendor ID, e.g. A00012345 (press Enter to skip)"

foreach ($value in @($naverClientId, $naverSecret, $coupangAccessKey, $coupangSecretKey, $coupangVendorId)) {
    if ($value -match "['`r`n]") { throw "An API value contains an unsupported character." }
}

$target = Join-Path $PSScriptRoot "..\config\marketplace-secrets.ps1"
$lines = @(
    "`$env:NAVER_COMMERCE_CLIENT_ID = '$naverClientId'",
    "`$env:NAVER_COMMERCE_CLIENT_SECRET = '$naverSecret'",
    "`$env:COUPANG_ACCESS_KEY = '$coupangAccessKey'",
    "`$env:COUPANG_SECRET_KEY = '$coupangSecretKey'",
    "`$env:COUPANG_VENDOR_ID = '$coupangVendorId'"
)
Set-Content -LiteralPath $target -Value $lines -Encoding UTF8
Write-Host "Saved: config\marketplace-secrets.ps1 (excluded from Git)"
Write-Host "Restart the ERP server, then select Get Products in Open Market Management."
