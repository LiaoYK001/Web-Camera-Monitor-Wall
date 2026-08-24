[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Artifact,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$Sha256,
    [Parameter(Mandatory)][string]$SigstoreBundle,
    [Parameter(Mandatory)][string]$InstallDirectory,
    [Parameter(Mandatory)][string]$Cosign,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$CosignSha256,
    [string]$IdentityRegexp = '^https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/.github/workflows/release-native-clients.yaml@refs/tags/v2\..+$',
    [string]$OidcIssuer = 'https://token.actions.githubusercontent.com'
)
$ErrorActionPreference = 'Stop'
$artifactPath = (Resolve-Path -LiteralPath $Artifact).Path
$bundlePath = (Resolve-Path -LiteralPath $SigstoreBundle).Path
$cosignPath = (Resolve-Path -LiteralPath $Cosign).Path
$destination = [IO.Path]::GetFullPath($InstallDirectory)
$parent = Split-Path -Parent $destination
if (-not [IO.Path]::IsPathFullyQualified($destination) -or -not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw 'Install directory must be an absolute path under an existing parent'
}
foreach ($path in @($artifactPath, $bundlePath, $cosignPath, $parent)) {
    if ((Get-Item -LiteralPath $path).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
        throw "Reparse points are not accepted in the update path: $path"
    }
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $artifactPath).Hash.ToLowerInvariant() -ne $Sha256) {
    throw 'Portable update SHA-256 mismatch'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $cosignPath).Hash.ToLowerInvariant() -ne $CosignSha256) {
    throw 'Reviewed cosign binary SHA-256 mismatch'
}
& $cosignPath verify-blob --bundle $bundlePath --certificate-identity-regexp $IdentityRegexp `
    --certificate-oidc-issuer $OidcIssuer $artifactPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Sigstore verification rejected the portable update' }

$staging = "$destination.staging"
$backup = "$destination.previous"
foreach ($path in @($staging, $backup)) {
    if (Test-Path -LiteralPath $path) {
        if ((Get-Item -LiteralPath $path).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing to replace reparse point $path"
        }
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $staging | Out-Null
Expand-Archive -LiteralPath $artifactPath -DestinationPath $staging
$executable = Join-Path $staging 'bin\webobs-native.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw 'Portable update lacks its executable' }
$oldPlatform = $env:QT_QPA_PLATFORM
try {
    $env:QT_QPA_PLATFORM = 'offscreen'
    & $executable --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Staged portable update self-check failed' }
    if (Test-Path -LiteralPath $destination) { Move-Item -LiteralPath $destination -Destination $backup }
    try {
        Move-Item -LiteralPath $staging -Destination $destination
    }
    catch {
        if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $destination }
        throw
    }
}
finally {
    $env:QT_QPA_PLATFORM = $oldPlatform
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}
Write-Host "Signed portable update installed; rollback directory: $backup"
