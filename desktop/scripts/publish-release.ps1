#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Tag,
    [Parameter(Mandatory)][string]$ArtifactDirectory,
    [string]$QualificationReceipts,
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
if ($QualificationReceipts) {
    & node (Join-Path $PSScriptRoot 'qualification.mjs') $QualificationReceipts $revision $version
    if ($LASTEXITCODE -ne 0) { throw 'Actual Windows 10 and 11 installation/media/update evidence did not pass.' }
} else {
    $smoke=Get-Content -LiteralPath (Join-Path $artifacts 'windows-install-smoke.json') -Raw | ConvertFrom-Json
    if ($smoke.schema -ne 1 -or $smoke.revision -ne $revision -or $smoke.version -ne $version -or @($smoke.checks.PSObject.Properties | Where-Object Value -ne 'passed').Count -or $smoke.checks.nsisInstall -ne 'passed' -or $smoke.checks.defaultUninstallDataRetention -ne 'passed') {throw 'Matching actual NSIS host smoke evidence is required.'}
    Write-Warning 'Host smoke only: clean Windows 10/11, real cameras and platform qualification remain outstanding; disclose this in the Release.'
}
$manifest = Get-Content -LiteralPath (Join-Path $artifacts "webobs-windows-$version-runtime-manifest.json") -Raw | ConvertFrom-Json
if ($manifest.revision -ne $revision -or $manifest.version -ne $version) { throw 'Runtime manifest does not match release identity.' }
$metadata=& node (Join-Path $PSScriptRoot 'update-metadata.mjs') $artifacts $version
if ($LASTEXITCODE -ne 0) {throw 'Stable NSIS update metadata failed verification.'}
$installerName=($metadata | ConvertFrom-Json).installer
$installer = Join-Path $artifacts $installerName
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($installerName.EndsWith('-UNSIGNED.exe')) {
    if ($signature.Status -ne 'NotSigned') {throw 'Unsigned release label does not match installer signature status.'}
} elseif (-not $env:WEBOBS_SIGNING_PUBLISHER -or $signature.Status -ne 'Valid' -or $signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false) -ne $env:WEBOBS_SIGNING_PUBLISHER) { throw 'Signed installer must have the configured valid Authenticode publisher.' }
$receipts = if($QualificationReceipts){Get-Content -LiteralPath $QualificationReceipts -Raw | ConvertFrom-Json}else{@($smoke)}
$installerDigest = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
foreach ($receipt in $receipts) { if ($receipt.installerSha256 -ne $installerDigest) { throw 'Installation evidence used a different installer.' } }
$approvedAssets = @($installerName,'latest.yml',"$installerName.blockmap","webobs-windows-$version-runtime-manifest.json","webobs-windows-$version-dependencies.lock.json","webobs-windows-$version-sbom.cdx.json","webobs-windows-$version-licenses.tar.gz","webobs-windows-$version-SHA256SUMS.txt")
foreach ($file in $approvedAssets) { if (-not (Test-Path -LiteralPath (Join-Path $artifacts $file) -PathType Leaf)) { throw "Required release asset missing: $file" } }
$checkedAssets = @()
foreach ($line in Get-Content -LiteralPath (Join-Path $artifacts "webobs-windows-$version-SHA256SUMS.txt")) {
    if ($line -notmatch '^([a-f0-9]{64})  ([A-Za-z0-9][A-Za-z0-9._-]{0,199})$') { throw 'Malformed asset checksum list.' }
    $expectedDigest=$Matches[1];$file=$Matches[2]
    if ($file -notin $approvedAssets -or $file -in $checkedAssets -or (Get-FileHash -LiteralPath (Join-Path $artifacts $file) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedDigest) { throw 'Release attachment digest mismatch.' }
    $checkedAssets += $file
}
foreach ($file in $approvedAssets | Where-Object {$_ -notlike '*-SHA256SUMS.txt'}) { if ($file -notin $checkedAssets) {throw 'Required attachment missing from checksum list.'} }
$sourceRoot = (Resolve-Path -LiteralPath $CorrespondingThirdPartySourceDirectory).Path
$sourceManifest = Get-Content -LiteralPath (Join-Path $sourceRoot 'SOURCE-MANIFEST.json') -Raw | ConvertFrom-Json
if ($sourceManifest.revision -ne $revision -or $sourceManifest.version -ne $version -or $sourceManifest.reviewed -ne $true -or $sourceManifest.files.Count -lt 1) { throw 'Reviewed matching bundled third-party sources are required for redistribution.' }
foreach ($file in $sourceManifest.files) {
    if ($file.name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.(?:tar\.gz|tar\.xz|zip)$' -or $file.name -in $approvedAssets -or $file.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Unsafe or colliding third-party source manifest.' }
    $source = Join-Path $sourceRoot $file.name
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) { throw 'Third-party source checksum mismatch.' }
    Copy-Item -LiteralPath $source -Destination (Join-Path $artifacts $file.name)
    $approvedAssets += $file.name
}
# Reuse the product's existing source and immutable attachment protocol.
$savedLocation = Get-Location
try {
    Set-Location -LiteralPath $repoRoot
    & bash './tests/run-public-audit.sh'; if ($LASTEXITCODE -ne 0) { throw 'Public release audit failed.' }
    $posixArtifacts = (& bash -c 'cygpath -u "$1"' _ $artifacts).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $posixArtifacts.StartsWith('/')) { throw 'Git Bash could not resolve the artifact directory.' }
    & bash './scripts/create-source-bundle.sh' $version $posixArtifacts; if ($LASTEXITCODE -ne 0) { throw 'Corresponding product source bundle failed.' }
    $approvedAssets += "webobs-source-$version.tar.gz","webobs-source-$version.tar.gz.sha256"
    $env:GITHUB_REPOSITORY = 'LiaoYK001/Web-Camera-Monitor-Wall'
    # The existing Release is shared with the container and must have this exact tag.
    $release = & gh release view $Tag --repo $env:GITHUB_REPOSITORY --json databaseId,tagName,targetCommitish | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $release.tagName -ne $Tag -or [string]$release.databaseId -notmatch '^[1-9][0-9]*$') { throw 'Create the matching product/container Release through the existing reviewed release flow first.' }
    $assets = $approvedAssets | ForEach-Object { (Join-Path $artifacts $_) -replace '\\','/' }
    if (-not $env:GH_TOKEN) { throw 'Use a maintainer GH_TOKEN only on the publishing host; it is never included in the client.' }
    # GitHub's REST tag lookup may return 404 for a Draft even though gh can
    # resolve it. Use the existing immutable numeric-ID upload protocol.
    & bash './scripts/upload-release-assets-immutable.sh' ([string]$release.databaseId) @assets
    if ($LASTEXITCODE -ne 0) { throw 'Immutable asset upload failed; already existing different assets were not overwritten.' }
} finally { Set-Location -LiteralPath $savedLocation }
