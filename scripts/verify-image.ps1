[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Image,
    [string]$Repository = 'LiaoYK001/Web-Camera-Monitor-Wall',
    [switch]$AllowLocalImage
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Assert-Condition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

Get-Command docker -ErrorAction Stop | Out-Null
if (-not $AllowLocalImage) {
    Assert-Condition ($Image -match '^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$') `
        'Production image references must use an immutable lowercase GHCR digest.'
    Get-Command gh -ErrorAction Stop | Out-Null
    docker pull $Image | Out-Null
    Assert-Condition ($LASTEXITCODE -eq 0) 'Unable to pull the candidate image digest.'
}

$InspectText = (@(docker image inspect $Image) -join '')
Assert-Condition ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($InspectText)) `
    'Candidate image is unavailable locally.'
$Inspect = @($InspectText | ConvertFrom-Json)[0]
$Labels = $Inspect.Config.Labels
Assert-Condition ($Inspect.Os -eq 'linux' -and $Inspect.Architecture -eq 'amd64') `
    'Candidate image must be linux/amd64.'
Assert-Condition ($Labels.'org.opencontainers.image.source' -eq "https://github.com/$Repository") `
    'Candidate image source label does not match the trusted repository.'
Assert-Condition ($Labels.'org.opencontainers.image.licenses' -eq 'GPL-2.0-or-later') `
    'Candidate image license label is missing or incorrect.'
Assert-Condition ($Labels.'org.opencontainers.image.revision' -match '^[0-9a-f]{40}$') `
    'Candidate image revision label must be a full Git commit.'
$Version = [string]$Labels.'org.opencontainers.image.version'
Assert-Condition ($Version -match '^[A-Za-z0-9._-]+$') 'Candidate image version label is invalid.'

if (-not $AllowLocalImage) {
    $ExpectedDigest = $Image.Substring($Image.LastIndexOf('@') + 1)
    Assert-Condition (@($Inspect.RepoDigests | Where-Object { $_ -like "*@$ExpectedDigest" }).Count -gt 0) `
        'Pulled image metadata does not contain the requested digest.'

    gh attestation verify "oci://$Image" --repo $Repository | Out-Null
    Assert-Condition ($LASTEXITCODE -eq 0) 'GitHub artifact attestation verification failed.'

    $TemporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ("webobs-source-verify-" + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($TemporaryDirectory) | Out-Null
    try {
        $ArchiveName = "webobs-source-$Version.tar.gz"
        $ReleaseBase = "https://github.com/$Repository/releases/download/$Version"
        $ArchivePath = Join-Path $TemporaryDirectory $ArchiveName
        $ChecksumPath = "$ArchivePath.sha256"
        Invoke-WebRequest -UseBasicParsing -Uri "$ReleaseBase/$ArchiveName" -OutFile $ArchivePath
        Invoke-WebRequest -UseBasicParsing -Uri "$ReleaseBase/$ArchiveName.sha256" -OutFile $ChecksumPath
        $ChecksumLine = [IO.File]::ReadAllText($ChecksumPath).Trim()
        Assert-Condition ($ChecksumLine -match "^(?<hash>[0-9a-f]{64})  $([Regex]::Escape($ArchiveName))$") `
            'Corresponding-source checksum sidecar has an invalid format.'
        $ActualHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        Assert-Condition ($ActualHash -eq $Matches.hash) 'Corresponding-source checksum verification failed.'

        $ScriptDirectory = Split-Path -Parent $PSCommandPath
        docker run --rm `
            -v "${TemporaryDirectory}:/release:ro" `
            -v "${ScriptDirectory}:/verify:ro" `
            ubuntu:24.04 sh /verify/verify-source-bundle.sh "/release/$ArchiveName" | Out-Null
        Assert-Condition ($LASTEXITCODE -eq 0) 'Corresponding-source archive structure verification failed.'
    } finally {
        if ([IO.Directory]::Exists($TemporaryDirectory)) {
            [IO.Directory]::Delete($TemporaryDirectory, $true)
        }
    }
}

Write-Host "Verified image identity, platform, license, revision, and source contract for $Version."
