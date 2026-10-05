# Stable Android identities from the v4.0 baseline; no publication side effects.
function Get-WebOBSAndroidReleaseIdentity {
    param([Parameter(Mandatory)][string]$Version)
    if ($Version -notmatch '\A(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\z') { throw 'Stable Android version must be A.B.C, without leading zeros or a development suffix.' }
    $major = [long]$Matches[1]; $minor = [long]$Matches[2]; $patch = [long]$Matches[3]
    $code = $major * 1000000 + $minor * 1000 + $patch
    if ($major -lt 4 -or $minor -gt 999 -or $patch -gt 999 -or $code -gt 2100000000) { throw 'Stable Android version exceeds the v4+ versionCode contract (minor/patch 0..999, code <= 2100000000).' }
    [pscustomobject]@{ Version = $Version; VersionCode = [int]$code }
}
