[CmdletBinding()]
param([int]$Port = 5173)
& node (Join-Path $PSScriptRoot 'dev.mjs') --stop --port "$Port"
exit $LASTEXITCODE
