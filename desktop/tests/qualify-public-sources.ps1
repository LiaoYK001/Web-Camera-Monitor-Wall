[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CandidateSource,
    [Parameter(Mandatory)][string]$ArtifactDirectory,
    [Parameter(Mandatory)][string]$ExpectedVersion,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedRevision,
    [Parameter(Mandatory)][string]$ReceiptDirectory
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$source = (Resolve-Path -LiteralPath $CandidateSource).Path
$artifactRoot = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
$manifests = @(Get-ChildItem -LiteralPath $artifactRoot -Recurse -File -Filter manifest.json |
    Where-Object { $_.FullName.Replace('\', '/').EndsWith('/resources/runtime/manifest.json') })
if ($manifests.Count -ne 1) { throw 'Require exactly one complete packaged runtime' }
$runtime = $manifests[0].DirectoryName
$identity = Get-Content -LiteralPath $manifests[0].FullName -Raw | ConvertFrom-Json
if ($identity.version -ne $ExpectedVersion -or $identity.revision -ne $ExpectedRevision) { throw 'Candidate identity mismatch' }
New-Item -ItemType Directory -Path $ReceiptDirectory -Force | Out-Null
$receipts = (Resolve-Path -LiteralPath $ReceiptDirectory).Path
Push-Location -LiteralPath $source
try {
    node --input-type=module -e "import {verifyRuntime} from './desktop/src/runtime-integrity.mjs';const m=await verifyRuntime(process.argv[1]);console.log(JSON.stringify({version:m.version,revision:m.revision,files:m.files.length,result:'verified'}));" $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Runtime integrity failed; refusing execution' }
    & (Join-Path $runtime 'python/python.exe') -B (Join-Path $PSScriptRoot 'public-source-network.py') --runtime $runtime --receipt (Join-Path $receipts 'network.json')
    if ($LASTEXITCODE -ne 0) { throw 'Network evidence collection failed' }
    $sources = @(
        @{ name='reported'; address='https://www.youtube.com/watch?v=eYDDvvGbhp8'; engine='auto' },
        @{ name='dw'; address='https://www.youtube.com/@DWNews/live'; engine='auto' },
        @{ name='aljazeera'; address='https://www.youtube.com/@AlJazeeraEnglish/live'; engine='auto' }
    )
    $failed = $false
    foreach ($entry in $sources) {
        $definition = Join-Path $env:RUNNER_TEMP ('webobs-public-source-' + $entry.name + '.json')
        ConvertTo-Json -InputObject @($entry) | Set-Content -LiteralPath $definition -Encoding utf8
        $receipt = Join-Path $receipts ($entry.name + '.json')
        # The candidate's own gate creates a fresh account/profile for every source.
        node desktop/tests/run-online-source-native.mjs --runtime $runtime --sources $definition --soak-seconds 120 --receipt $receipt
        if ($LASTEXITCODE -ne 0) { $failed = $true; continue }
        $result = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
        if ($result.result -ne 'passed' -or $result.runtimeRevision -ne $ExpectedRevision -or $result.frontendOverride -or
            $result.browserPermissionScope -ne 'none' -or $result.frontendDocumentsVerified -ne 2 -or
            $result.receipts.Count -ne 1 -or -not $result.receipts[0].restartFramePresented -or
            $result.receipts[0].soak.seconds -lt 120) { $failed = $true }
    }
    $network = Get-Content -LiteralPath (Join-Path $receipts 'network.json') -Raw | ConvertFrom-Json
    if (@($network.sources | Where-Object { $_.name -ne 'reported' -and $_.isLive -eq $true -and $_.formatCount -gt 0 }).Count -eq 0) { $failed = $true }
    if ($failed) { throw 'Public source qualification incomplete; retain redacted receipts, never publish' }
} finally { Pop-Location }
