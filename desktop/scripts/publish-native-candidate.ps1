#requires -Version 7.2
# Publish one frozen 5.0.0-rc.N complete candidate as a GitHub prerelease.
# Never modifies v4.5, never marks Latest and never opens the stable feed.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][string]$Manifest,
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$Repository,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceRevision,
    [Parameter(Mandatory=$true)][string]$Notes,
    [switch]$Confirm
)
$ErrorActionPreference = 'Stop'
if (-not $Confirm) { throw 'Explicit -Confirm is required; candidate publication is never automatic.' }
if ($Version -notmatch '^5\.[01]\.0-rc\.[0-9]+$') { throw 'Candidate version must be 5.0.0-rc.N or 5.1.0-rc.N.' }
$installer = (Resolve-Path -LiteralPath $Installer).Path
$manifestPath = (Resolve-Path -LiteralPath $Manifest).Path
$notesPath = (Resolve-Path -LiteralPath $Notes).Path
if ((Split-Path -Leaf $installer) -notmatch '^WebOBS-Wall-.+-windows-x64-SETUP\.exe$') {
    throw 'Unexpected complete installer name.'
}
if ((Split-Path -Leaf $manifestPath) -ne 'latest.yml') { throw 'Update metadata must be latest.yml.' }
$tag = "v$Version"
& gh release view $tag --repo $Repository 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { throw 'Candidate tag/release already exists; never overwrite it.' }
& gh api "repos/$Repository/git/ref/tags/$tag" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { throw 'Candidate tag already exists.' }
$sha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$sha512 = [Convert]::ToBase64String([Security.Cryptography.SHA512]::Create().ComputeHash([IO.File]::ReadAllBytes($installer)))
$size = (Get-Item -LiteralPath $installer).Length
$text = Get-Content -LiteralPath $manifestPath -Raw
if ($text -notmatch "(?m)^version:\s*$([regex]::Escape($Version))\s*$" -or
    $text -notmatch "(?m)^\s+size:\s*$size\s*$" -or
    $text -notmatch [regex]::Escape($sha512)) {
    throw 'latest.yml does not match the frozen installer bytes.'
}
$checksums = Join-Path (Split-Path -Parent $installer) 'SHA256SUMS.txt'
"$sha256  $(Split-Path -Leaf $installer)" | Set-Content -LiteralPath $checksums -Encoding ascii
$args = @('release','create',$tag,$installer,$manifestPath,$checksums,
    '--repo',$Repository,'--title',"WebOBS Wall $Version 完整候选 / complete candidate",
    '--notes-file',$notesPath,'--target',$SourceRevision,'--prerelease','--latest=false')
& gh @args
if ($LASTEXITCODE -ne 0) { throw 'Candidate release creation failed.' }
Write-Output "Published $tag prerelease from $((Get-Item -LiteralPath $installer).FullName) ($size bytes, sha256 $sha256)."
