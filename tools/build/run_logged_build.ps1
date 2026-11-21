[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $BuildScript,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $LogFile
)

$ErrorActionPreference = 'Stop'

$resolvedBuildScript = (Resolve-Path -LiteralPath $BuildScript).Path
$logDirectory = Split-Path -Parent $LogFile
if (-not (Test-Path -LiteralPath $logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
}

$resolvedLogDirectory = (Resolve-Path -LiteralPath $logDirectory).Path
$resolvedLogFile = Join-Path $resolvedLogDirectory (Split-Path -Leaf $LogFile)

$commandLine = 'call "{0}" --logged 2>&1' -f $resolvedBuildScript.Replace('"', '""')

# Tee-Object on Windows PowerShell 5.1 has no -Encoding and writes UTF-16LE,
# which doubles the log size and makes it invisible to grep/findstr and to any
# log parser that assumes bytes. Write UTF-8 (no BOM) by hand instead.
$writer = New-Object System.IO.StreamWriter(
    $resolvedLogFile,
    $false,
    (New-Object System.Text.UTF8Encoding($false)))
try {
    & $env:ComSpec /d /s /c $commandLine | ForEach-Object {
        Write-Host $_
        $writer.WriteLine($_)
    }
    $buildExit = $LASTEXITCODE
}
finally {
    $writer.Flush()
    $writer.Dispose()
}

if ($null -eq $buildExit) {
    $buildExit = 1
}

exit $buildExit
