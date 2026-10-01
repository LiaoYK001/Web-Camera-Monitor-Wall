#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Tag,
    [Parameter(Mandatory)][string]$ArtifactDirectory,
    [Parameter(Mandatory)][string]$QualificationReceipts,
    [Parameter(Mandatory)][string]$CorrespondingThirdPartySourceDirectory
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ($Tag -notmatch '^v(\d+)\.(\d+)(?:\.(\d+))?$') { throw 'Tag must be vX.Y or vX.Y.Z.' }
$version = if ($Matches[3]) {"$($Matches[1]).$($Matches[2]).$($Matches[3])"} else {"$($Matches[1]).$($Matches[2]).0"}
$artifacts = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
$revision = (& git -C $repoRoot rev-parse "$Tag^{commit}").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Use an existing reviewed product/container release tag.' }
if ((& git -C $repoRoot rev-parse HEAD).Trim() -ne $revision) { throw 'Checkout must match the release tag exactly.' }
& node (Join-Path $PSScriptRoot 'qualification.mjs') $QualificationReceipts $revision $version
if ($LASTEXITCODE -ne 0) { throw 'Actual Windows 10 and 11 installation/media/update evidence is required.' }
$manifest = Get-Content -LiteralPath (Join-Path $artifacts "webobs-windows-$version-runtime-manifest.json") -Raw | ConvertFrom-Json
if ($manifest.revision -ne $revision -or $manifest.version -ne $version) { throw 'Runtime manifest does not match release identity.' }
$installer = Join-Path $artifacts "WebOBS-$version-windows-x64.exe"
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if (-not $env:WEBOBS_SIGNING_PUBLISHER -or $signature.Status -ne 'Valid' -or $signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false) -ne $env:WEBOBS_SIGNING_PUBLISHER) { throw 'Official installer must have the configured valid Authenticode publisher.' }
$receipts = Get-Content -LiteralPath $QualificationReceipts -Raw | ConvertFrom-Json
$installerDigest = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
foreach ($receipt in $receipts) { if ($receipt.installerSha256 -ne $installerDigest) { throw 'Installation evidence used a different installer.' } }
foreach ($file in @('latest.yml',"WebOBS-$version-windows-x64.exe.blockmap","webobs-windows-$version-sbom.cdx.json","webobs-windows-$version-licenses.tar.gz","webobs-windows-$version-SHA256SUMS.txt")) { if (-not (Test-Path -LiteralPath (Join-Path $artifacts $file) -PathType Leaf)) { throw "Required release asset missing: $file" } }
$sourceRoot = (Resolve-Path -LiteralPath $CorrespondingThirdPartySourceDirectory).Path
$sourceManifest = Get-Content -LiteralPath (Join-Path $sourceRoot 'SOURCE-MANIFEST.json') -Raw | ConvertFrom-Json
if ($sourceManifest.revision -ne $revision -or $sourceManifest.version -ne $version -or $sourceManifest.reviewed -ne $true -or $sourceManifest.files.Count -lt 1) { throw 'Reviewed matching bundled third-party sources are required for redistribution.' }
foreach ($file in $sourceManifest.files) {
    if ($file.name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$' -or $file.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Unsafe third-party source manifest.' }
    $source = Join-Path $sourceRoot $file.name
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) { throw 'Third-party source checksum mismatch.' }
    Copy-Item -LiteralPath $source -Destination (Join-Path $artifacts $file.name)
}
# Reuse the product's existing source and immutable attachment protocol.
$savedLocation = Get-Location
try {
    Set-Location -LiteralPath $repoRoot
    & bash './tests/run-public-audit.sh'; if ($LASTEXITCODE -ne 0) { throw 'Public release audit failed.' }
    $posixArtifacts = (& bash -c 'cygpath -u "$1"' _ $artifacts).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $posixArtifacts.StartsWith('/')) { throw 'Git Bash could not resolve the artifact directory.' }
    & bash './scripts/create-source-bundle.sh' $version $posixArtifacts; if ($LASTEXITCODE -ne 0) { throw 'Corresponding product source bundle failed.' }
    $env:GITHUB_REPOSITORY = 'LiaoYK001/Web-Camera-Monitor-Wall'
    # The existing Release is shared with the container and must have this exact tag.
    & gh release view $Tag --repo $env:GITHUB_REPOSITORY --json tagName,targetCommitish; if ($LASTEXITCODE -ne 0) { throw 'Create the product/container Release through the existing reviewed release flow first.' }
    $assets = Get-ChildItem -LiteralPath $artifacts -File | Where-Object { $_.Name -match '^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$' } | ForEach-Object { $_.FullName -replace '\\','/' }
    if (-not $env:GH_TOKEN) { throw 'Use a maintainer GH_TOKEN only on the publishing host; it is never included in the client.' }
    & bash './scripts/upload-release-assets-immutable.sh' $Tag @assets
    if ($LASTEXITCODE -ne 0) { throw 'Immutable asset upload failed; already existing different assets were not overwritten.' }
} finally { Set-Location -LiteralPath $savedLocation }
