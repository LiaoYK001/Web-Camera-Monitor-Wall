[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Image,
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$Prerelease,
    [switch]$PrepareOnly
)

$ErrorActionPreference = 'Stop'
if ($Image -cnotmatch '^ghcr\.io/[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}$') {
    throw 'Image must be ghcr.io/owner/repository in lowercase.'
}
if ($Version -ne 'dev' -and $Version -cnotmatch '^v[0-9]+\.[0-9]+(?:\.[0-9]+)?$') {
    throw 'Version must be dev, vX.Y, or vX.Y.Z.'
}
if ($Prerelease -and $Version -cnotin @('v3.0', 'v3.0.1')) {
    throw '-Prerelease is restricted to v3.0 and v3.0.1; v3.1 and later are stable releases.'
}

$repositoryRoot = (git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repositoryRoot) { throw 'Not inside a Git repository.' }
Set-Location (Resolve-Path -LiteralPath $repositoryRoot).Path

# Prefer Git for Windows Bash: WindowsApps\bash.exe forwards to WSL and cannot
# resolve the Windows linked-worktree .git path used by the release checkout.
$git = Get-Command git.exe -ErrorAction SilentlyContinue
$gitBashPath = $null
if ($git) {
    $candidate = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $git.Source) '..\bin\bash.exe'))
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $gitBashPath = $candidate }
}
if ($gitBashPath) {
    $bashPath = $gitBashPath
} else {
    $bash = Get-Command bash.exe -ErrorAction SilentlyContinue
    if (-not $bash) {
        throw 'Git for Windows bash.exe is required by the deterministic source-bundle publisher.'
    }
    if ($bash.Source -match '\\Microsoft\\WindowsApps\\bash(?:\.exe)?$') {
        throw 'Git for Windows Bash is required; the WindowsApps bash.exe alias launches WSL and cannot read the linked release worktree.'
    }
    $bashPath = $bash.Source
}

# Positional parameters avoid command-string interpolation of image, tag, or
# token values. GH_TOKEN remains process-local and is never put on argv.
$previousPrepareOnly = $env:WEBOBS_RELEASE_PREPARE_ONLY
try {
    if ($PrepareOnly) { $env:WEBOBS_RELEASE_PREPARE_ONLY = 'true' }
    if ($Prerelease) {
        & $bashPath -c './scripts/release-image-local.sh "$1" "$2" --prerelease' -- $Image $Version
    } else {
        & $bashPath -c './scripts/release-image-local.sh "$1" "$2"' -- $Image $Version
    }
    $publicationExitCode = $LASTEXITCODE
} finally {
    $env:WEBOBS_RELEASE_PREPARE_ONLY = $previousPrepareOnly
}
if ($publicationExitCode -ne 0) { exit $publicationExitCode }
