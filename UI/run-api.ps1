param([int]$ApiPort = 8000)

$ErrorActionPreference = 'Stop'
$repositoryPath = Split-Path -Parent $PSScriptRoot
$temporaryRuntime = Join-Path $env:TEMP 'jmap-api-runtime'
if (Test-Path -LiteralPath $temporaryRuntime) {
    $env:PYTHONPATH = $temporaryRuntime + [IO.Path]::PathSeparator + $env:PYTHONPATH
}
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location -LiteralPath $repositoryPath
try {
    python -B -m uvicorn UI.api_loader:app --reload --port $ApiPort
} finally {
    Pop-Location
}
