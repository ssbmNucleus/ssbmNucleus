#Requires -Version 5.1
<#
Fail a signed Windows build BEFORE the expensive stages when electron-builder
has no identity it can actually use.

This must mirror app-builder-lib exactly, or it is theatre.  On Windows,
out/codeSign/windowsSignToolManager.js resolves `cscInfo` from, in order:

  1. build.win.signtoolOptions.certificateSubjectName / .certificateSha1
     (looked up in the Windows certificate store by signtool)
  2. build.win.signtoolOptions.certificateFile (+ CSC_KEY_PASSWORD)
  3. the WIN_CSC_LINK / CSC_LINK environment variables

Nothing else.  In particular CSC_IDENTITY_AUTO_DISCOVERY is read only by
out/util/flags.js and consumed only by macCodeSign.js -- it is dead on the
Windows path -- so "there is a code-signing cert in Cert:\CurrentUser\My"
does NOT mean electron-builder will find it.  A preflight that accepts that
passes, then winPackager.js throws at the very end with forceCodeSigning.
#>

[CmdletBinding()]
param(
    [string] $PackageJson
)

$ErrorActionPreference = 'Stop'

# $PSScriptRoot is not bound yet while param defaults are evaluated on
# Windows PowerShell 5.1, so resolve the default here instead.
if ([string]::IsNullOrWhiteSpace($PackageJson)) {
    $PackageJson = Join-Path (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'app') 'package.json'
}

function Fail([string] $message) {
    Write-Host "ERROR: $message"
    Write-Host ''
    Write-Host 'Signed builds need an identity electron-builder can resolve. Use ONE of:'
    Write-Host '  - set WIN_CSC_LINK to a .pfx path (or base64) plus WIN_CSC_KEY_PASSWORD'
    Write-Host '  - add build.win.signtoolOptions.certificateSubjectName (or .certificateSha1)'
    Write-Host '    to package.json for a certificate installed in the Windows store'
    Write-Host '  - add build.win.signtoolOptions.certificateFile to package.json'
    Write-Host ''
    Write-Host 'For a local-only test package, set NUCLEUS_ALLOW_UNSIGNED=1 instead.'
    exit 1
}

if (-not (Test-Path -LiteralPath $PackageJson)) {
    Fail "package.json not found at $PackageJson"
}

$signtool = $null
try {
    $pkg = Get-Content -LiteralPath $PackageJson -Raw | ConvertFrom-Json
    if ($pkg.build -and $pkg.build.win) { $signtool = $pkg.build.win.signtoolOptions }
} catch {
    Fail "package.json could not be parsed: $($_.Exception.Message)"
}

function Get-Prop($obj, [string] $name) {
    if ($null -eq $obj) { return $null }
    $p = $obj.PSObject.Properties[$name]
    if ($null -eq $p) { return $null }
    if ($p.Value -is [string] -and [string]::IsNullOrWhiteSpace($p.Value)) { return $null }
    return $p.Value
}

$subjectName = Get-Prop $signtool 'certificateSubjectName'
$sha1        = Get-Prop $signtool 'certificateSha1'
$certFile    = Get-Prop $signtool 'certificateFile'

$now = Get-Date

function Test-StoreCertificate {
    param([string] $Subject, [string] $Sha1)

    $stores = @('Cert:\CurrentUser\My', 'Cert:\LocalMachine\My')
    foreach ($store in $stores) {
        $candidates = @(Get-ChildItem -Path $store -CodeSigningCert -ErrorAction SilentlyContinue)
        foreach ($cert in $candidates) {
            if ($Sha1 -and $cert.Thumbprint -ne ($Sha1 -replace '\s', '')) { continue }
            if ($Subject -and $cert.Subject -notlike "*$Subject*") { continue }
            if (-not $cert.HasPrivateKey) { continue }
            if ($cert.NotBefore -gt $now -or $cert.NotAfter -le $now) { continue }
            return $cert
        }
    }
    return $null
}

if ($subjectName -or $sha1) {
    $cert = Test-StoreCertificate -Subject $subjectName -Sha1 $sha1
    if ($null -eq $cert) {
        $which = if ($sha1) { "certificateSha1 '$sha1'" } else { "certificateSubjectName '$subjectName'" }
        Fail "package.json declares $which, but no current code-signing certificate with a private key matches it in CurrentUser\My or LocalMachine\My."
    }
    Write-Host "Signing identity: store certificate $($cert.Subject) (expires $($cert.NotAfter.ToString('yyyy-MM-dd')))."
    exit 0
}

# certificateFile and WIN_CSC_LINK/CSC_LINK both end up as a .pfx electron-builder
# imports; validate whichever one is configured.
$pfx = $certFile
$pfxSource = 'build.win.signtoolOptions.certificateFile'
if (-not $pfx) {
    foreach ($name in @('WIN_CSC_LINK', 'CSC_LINK')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $pfx = $value
            $pfxSource = $name
            break
        }
    }
}

if (-not $pfx) {
    Fail 'forceCodeSigning is enabled, but electron-builder has no Windows signing identity. A certificate installed in Cert:\CurrentUser\My is NOT discovered on Windows (CSC_IDENTITY_AUTO_DISCOVERY is macOS-only).'
}

# A link may be an https URL or base64 payload rather than a path; only a
# local path can be opened and checked here.
$looksLikePath = ($pfx -notmatch '^https?://') -and ($pfx.Length -lt 260)
if (-not $looksLikePath) {
    Write-Host "Signing identity: $pfxSource is a remote or inline certificate; electron-builder will resolve it."
    exit 0
}

if (-not (Test-Path -LiteralPath $pfx)) {
    Fail "$pfxSource points at '$pfx', which does not exist."
}

$password = $null
foreach ($name in @('WIN_CSC_KEY_PASSWORD', 'CSC_KEY_PASSWORD')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not [string]::IsNullOrWhiteSpace($value)) { $password = $value; break }
}

try {
    $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $pfx).Path)
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2
    if ($null -eq $password) {
        $cert.Import($bytes)
    } else {
        $cert.Import($bytes, $password, 'DefaultKeySet')
    }
} catch {
    Fail "$pfxSource could not be opened: $($_.Exception.Message). If it is password-protected, set WIN_CSC_KEY_PASSWORD."
}

if (-not $cert.HasPrivateKey) {
    Fail "$pfxSource ('$pfx') contains no private key, so signtool cannot sign with it."
}
if ($cert.NotBefore -gt $now) {
    Fail "$pfxSource certificate is not valid until $($cert.NotBefore.ToString('yyyy-MM-dd'))."
}
if ($cert.NotAfter -le $now) {
    Fail "$pfxSource certificate expired on $($cert.NotAfter.ToString('yyyy-MM-dd'))."
}

Write-Host "Signing identity: $pfxSource -> $($cert.Subject) (expires $($cert.NotAfter.ToString('yyyy-MM-dd')))."
exit 0
