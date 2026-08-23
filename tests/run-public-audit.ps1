[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ExpectedObsCommit = 'fb4d98bf88fae5fc85cb11fc57f7c5e309282194'
$ExpectedObsUrl = 'https://github.com/obsproject/obs-studio.git'

function Invoke-GitCapture {
    param(
        [string[]]$Arguments,
        [int[]]$AllowedExitCodes = @(0)
    )

    $output = @(& git @Arguments 2>$null)
    $status = $LASTEXITCODE
    if ($AllowedExitCodes -notcontains $status) {
        throw "Git command failed during the public-repository audit (exit $status)."
    }
    return [PSCustomObject]@{
        Output = $output
        Status = $status
    }
}

function Assert-IndexLines {
    param(
        [string]$Path,
        [string[]]$RequiredLines
    )

    $result = Invoke-GitCapture -Arguments @('show', ":$Path")
    $lines = @($result.Output | ForEach-Object { $_.ToString() })
    foreach ($requiredLine in $RequiredLines) {
        if ($lines -cnotcontains $requiredLine) {
            throw "Public-repository audit failed: '$Path' is missing required protection '$requiredLine'."
        }
    }
}

Get-Command git -ErrorAction Stop | Out-Null

Push-Location $RepositoryRoot
try {
    $rootResult = Invoke-GitCapture -Arguments @('rev-parse', '--show-toplevel')
    $gitRoot = (Resolve-Path -LiteralPath $rootResult.Output[0].ToString()).Path
    if (-not $gitRoot.Equals($RepositoryRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The public-repository audit must run from this repository.'
    }

    $trackedResult = Invoke-GitCapture -Arguments @('-c', 'core.quotepath=false', 'ls-files')
    $trackedFiles = @($trackedResult.Output | ForEach-Object { $_.ToString().Replace('\', '/') })
    $pathViolations = [Collections.Generic.List[string]]::new()
    $blockedExtensions = @('.key', '.pem', '.p12', '.pfx', '.mp4', '.mkv', '.mov', '.avi', '.m4v', '.log')

    foreach ($path in $trackedFiles) {
        $leaf = [IO.Path]::GetFileName($path)
        $extension = [IO.Path]::GetExtension($path).ToLowerInvariant()
        $isEnvFile = $leaf.StartsWith('.env', [StringComparison]::OrdinalIgnoreCase) -and
            $path -cne '.env.example'
        $isSecretDirectory = $path.StartsWith('secrets/', [StringComparison]::OrdinalIgnoreCase) -or
            $path.IndexOf('/secrets/', [StringComparison]::OrdinalIgnoreCase) -ge 0
        $isBackup = $path.StartsWith('backups/', [StringComparison]::OrdinalIgnoreCase)
        $isRecording = $path.StartsWith('recordings/', [StringComparison]::OrdinalIgnoreCase) -and
            $path -cne 'recordings/.gitkeep'
        $isArtifact = $path.StartsWith('tests/artifacts/', [StringComparison]::OrdinalIgnoreCase) -and
            $path -cne 'tests/artifacts/.gitkeep'
        $isBuildDirectory = $path.StartsWith('build/', [StringComparison]::OrdinalIgnoreCase) -or
            $path -match '^(?i:build-[^/]+)/'
        $isWebBuild = $path.StartsWith('web/node_modules/', [StringComparison]::OrdinalIgnoreCase) -or
            $path.StartsWith('web/dist/', [StringComparison]::OrdinalIgnoreCase)

        if ($isEnvFile -or $isSecretDirectory -or $isBackup -or $isRecording -or $isArtifact -or $isBuildDirectory -or $isWebBuild -or
            $blockedExtensions -contains $extension) {
            $pathViolations.Add($path)
        }
    }
    if ($pathViolations.Count -gt 0) {
        throw "Public-repository audit failed: sensitive or generated paths are tracked: $($pathViolations -join ', ')."
    }

    Assert-IndexLines -Path '.gitignore' -RequiredLines @(
        '/.env*',
        '!/.env.example',
        '/secrets/',
        '/backups/',
        '*.key',
        '*.pem',
        '*.p12',
        '*.pfx',
        '/build/',
        '/build-*/',
        '/web/node_modules/',
        '/web/dist/',
        '/recordings/*',
        '!/recordings/.gitkeep',
        '/tests/artifacts/*',
        '!/tests/artifacts/.gitkeep'
    )
    Assert-IndexLines -Path '.dockerignore' -RequiredLines @(
        '.git',
        '**/.env*',
        '!.env.example',
        '**/secrets/**',
        'backups',
        '**/*.key',
        '**/*.pem',
        '**/*.p12',
        '**/*.pfx',
        'build',
        'build-*',
        'web/node_modules',
        'web/dist',
        'recordings/*',
        '!recordings/.gitkeep',
        'tests/artifacts/*',
        '!tests/artifacts/.gitkeep'
    )

    $secretPattern = '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-(proj-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}'
    $secretResult = Invoke-GitCapture -Arguments @('grep', '--cached', '-I', '-l', '-E', '--', $secretPattern, '--', '.') -AllowedExitCodes @(0, 1)
    if ($secretResult.Status -eq 0) {
        $secretFiles = @($secretResult.Output | ForEach-Object { $_.ToString() })
        throw "Public-repository audit failed: high-confidence credential or private-key material exists in the Git index: $($secretFiles -join ', ')."
    }

    $allowedRtspReferences = @{
        '.env.example'                = @('user:password')
        'docker/Dockerfile'           = @('user:password', '***:***')
        'README.md'                   = @('user:password', '***:***')
        'core/tests/common_tests.cpp' = @('user:password', '***:***', 'user', '***', 'name:p%40ss', 'u:p', 'x:y')
        'tests/run-contracts.ps1'     = @('test-user:supersecret', '***:***')
        'tests/run-contracts.sh'      = @('test-user:supersecret', '***:***')
        'tests/run-real-camera.ps1'   = @('user:password')
        'tests/run-real-camera.sh'    = @('user:password')
    }
    $rtspPattern = 'rtsps?://[^[:space:]/@]+(:[^[:space:]/@]*)?@'
    $rtspResult = Invoke-GitCapture -Arguments @('grep', '--cached', '-I', '-n', '-o', '-E', '--', $rtspPattern, '--', '.') -AllowedExitCodes @(0, 1)
    $rtspViolations = [Collections.Generic.List[string]]::new()
    if ($rtspResult.Status -eq 0) {
        foreach ($record in $rtspResult.Output) {
            $match = [Regex]::Match($record.ToString(), '^([^:]+):([0-9]+):(rtsps?://.*@)$')
            if (-not $match.Success) {
                throw 'Public-repository audit could not safely parse an RTSP reference from the Git index.'
            }

            $path = $match.Groups[1].Value
            $lineNumber = $match.Groups[2].Value
            $url = $match.Groups[3].Value
            $schemeEnd = $url.IndexOf('://', [StringComparison]::Ordinal) + 3
            $userinfo = $url.Substring($schemeEnd, $url.Length - $schemeEnd - 1)
            $allowedValues = $allowedRtspReferences[$path]
            if ($null -eq $allowedValues -or $allowedValues -cnotcontains $userinfo) {
                $rtspViolations.Add("${path}:$lineNumber")
            }
        }
    }
    if ($rtspViolations.Count -gt 0) {
        throw "Public-repository audit failed: non-placeholder RTSP credentials exist in the Git index at $($rtspViolations -join ', ')."
    }

    $indexResult = Invoke-GitCapture -Arguments @('ls-files', '--stage')
    $indexEntries = @($indexResult.Output | ForEach-Object { $_.ToString() })
    $submoduleEntries = @($indexEntries | Where-Object { $_ -like '160000 *' })
    $expectedEntry = "160000 $ExpectedObsCommit 0`tobs/obs-studio"
    if ($submoduleEntries.Count -ne 1 -or $submoduleEntries[0] -cne $expectedEntry) {
        throw 'Public-repository audit failed: OBS must be the only root submodule and remain pinned to the approved commit.'
    }

    foreach ($executablePath in @(
        'gateway/transcode-on-demand.sh',
        'tests/run-contracts.sh',
        'tests/run-public-audit.sh',
        'tests/run-m1-real-camera.sh',
        'tests/run-m10-real-mjpeg.sh',
        'tests/run-real-camera.sh',
        'tests/run-smoke.sh',
        'tests/rtsp-fixture/publish-hevc.sh'
    )) {
        if (@($indexEntries | Where-Object { $_ -match "^100755 [0-9a-f]{40} 0`t$([Regex]::Escape($executablePath))$" }).Count -ne 1) {
            throw "Public-repository audit failed: '$executablePath' must remain executable in the Git index."
        }
    }

    $gitmodulesResult = Invoke-GitCapture -Arguments @('show', ':.gitmodules')
    $gitmodulesLines = @($gitmodulesResult.Output | ForEach-Object { $_.ToString().Trim() })
    if ($gitmodulesLines -cnotcontains 'path = obs/obs-studio' -or
        $gitmodulesLines -cnotcontains "url = $ExpectedObsUrl") {
        throw 'Public-repository audit failed: the OBS submodule path or public upstream URL changed.'
    }

    $checkoutResult = Invoke-GitCapture -Arguments @('submodule', 'status', '--recursive')
    $checkoutLines = @($checkoutResult.Output | ForEach-Object { $_.ToString() })
    if ($checkoutLines.Count -eq 0 -or @($checkoutLines | Where-Object { $_.Length -eq 0 -or $_[0] -ne ' ' }).Count -gt 0) {
        throw 'Public-repository audit failed: recursively initialize submodules and restore their pinned commits.'
    }

    Write-Host "Public repository audit passed: $($trackedFiles.Count) indexed paths, approved RTSP placeholders only, OBS pin $ExpectedObsCommit."
}
finally {
    Pop-Location
}
