param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("a", "b")]
    [string]$Branch
)

$ErrorActionPreference = "Stop"
$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$GitPrefix = @("-c", "safe.directory=$RepoPath", "-C", $RepoPath)

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & git @GitPrefix @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

$changes = & git @GitPrefix status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw "This folder is not a Git working tree."
}
if ($changes) {
    throw "Uncommitted changes exist. Finish or preserve them before synchronizing."
}

Invoke-Git fetch --prune origin
Invoke-Git switch $Branch
Invoke-Git pull --ff-only origin $Branch
Invoke-Git merge --ff-only origin/main
Invoke-Git push origin $Branch

Write-Host "Branch $Branch is synchronized with origin/main."
