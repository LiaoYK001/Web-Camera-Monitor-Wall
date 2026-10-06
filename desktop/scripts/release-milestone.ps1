function Resolve-WebOBSDesktopMilestone {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Version,
          [Parameter(Mandatory)][bool]$Release,
          [AllowEmptyString()][string]$Milestone = '')
    if ($Version -notmatch '\A(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})(-dev\.[0-9A-Za-z.-]+)?\z') { throw 'Invalid desktop release identity.' }
    $major = [long]$Matches[1]
    if ($Release -eq $Version.Contains('-dev.')) { throw 'Desktop version and release/development class do not match.' }
    if ($major -lt 4 -and -not $Milestone) { return 'v3-M2-dev' } # Preserve historical build identity.
    $suffix = if ($Release) { '' } else { '-dev' }
    if (-not $Milestone -or $Milestone -notmatch "\Av${major}-M[1-9][0-9]*${suffix}\z") {
        throw 'Desktop v4+ requires an explicit matching reviewed milestone, with -dev only for development builds.'
    }
    return $Milestone
}
