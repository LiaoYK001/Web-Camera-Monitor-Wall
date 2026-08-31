[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Image,
    [Parameter(Mandatory = $true)][string]$Version
)

$ErrorActionPreference = 'Stop'
if ($Image -cnotmatch '^ghcr\.io/[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}$') {
    throw 'Image must be ghcr.io/owner/repository in lowercase.'
}
if ($Version -ne 'dev' -and $Version -cnotmatch '^v[0-9]+\.[0-9]+(?:\.[0-9]+)?$') {
    throw 'Version must be dev, vX.Y, or vX.Y.Z.'
}

$repositoryRoot = (git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repositoryRoot) { throw 'Not inside a Git repository.' }
Set-Location (Resolve-Path -LiteralPath $repositoryRoot).Path

$bash = Get-Command bash.exe -ErrorAction SilentlyContinue
if (-not $bash) {
    $git = Get-Command git.exe -ErrorAction Stop
    $candidate = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $git.Source) '..\bin\bash.exe'))
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw 'Git for Windows bash.exe is required by the deterministic source-bundle publisher.'
    }
    $bashPath = $candidate
} else {
    $bashPath = $bash.Source
}

# Positional parameters avoid command-string interpolation of image, tag, or
# token values. GH_TOKEN remains process-local and is never put on argv.
& $bashPath -c './scripts/release-image-local.sh "$1" "$2"' -- $Image $Version
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
