<#
.SYNOPSIS
Sets up this checkout as the Nucleus creation toolkit, so SSBM Nucleus can run native_port and stage_workbench.

.DESCRIPTION
The installed app lists native_port and stage_workbench to the user's own AI (MCP, docs/dev/APP_MCP.md) and
forwards their calls to tools/harness/harness_mcp.py in a source checkout. This script prepares that checkout:

  1. finds Python 3.13 and makes the venv app\venv (kept if it exists);
  2. installs app\requirements.txt and tools\creation\requirements.txt into it;
  3. fetches the pinned MexCLI and HSDRawViewer builds (tools\build\fetch_native.py all);
  4. checks for the .NET SDK, which stage_workbench needs to build its stage tool.

Then tell your AI to call connect_creation_toolkit with this folder. Nothing here downloads a game: the source
games are your own, read from where you installed them. Short guide: tools\creation\SETUP.md.

.PARAMETER Python
A Python 3.13 interpreter to make the venv with. Default: the py launcher's 3.13, else python on PATH.

.PARAMETER SkipNative
Skip step 3 (for example when app\utility already holds MexCLI and HSDRawViewer).

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File tools\creation\setup.ps1

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File tools\creation\setup.ps1 -WhatIf
Shows each step without changing anything.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Python,
    [switch]$SkipNative
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Venv = Join-Path $Root 'app\venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Requirements = @((Join-Path $Root 'app\requirements.txt'), (Join-Path $Root 'tools\creation\requirements.txt'))

function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Failed ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

# The interpreter as a command plus leading arguments, or $null.
function Find-Python {
    if ($Python) { return , @($Python) }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.13 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { return , @('py', '-3.13') }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($version -eq '3.13') { return , @('python') }
    }
    return $null
}

foreach ($needed in @('tools\harness\harness_mcp.py', 'app\requirements.txt', 'tools\build\fetch_native.py')) {
    if (-not (Test-Path (Join-Path $Root $needed))) {
        throw "$Root is not a whole Nucleus creation toolkit checkout: $needed is missing."
    }
}
Write-Host "Nucleus creation toolkit: $Root"

Step '1/4 Python 3.13 and the venv'
if (Test-Path $VenvPython) {
    Write-Host "Keeping the venv at $Venv"
} else {
    $found = Find-Python
    if (-not $found) {
        throw 'Python 3.13 was not found. Install Python 3.13 from https://www.python.org/downloads/ (or pass -Python <path to python.exe>), then run this again.'
    }
    $exe = $found[0]
    $lead = @($found | Select-Object -Skip 1)
    Write-Host "Python: $($found -join ' ')"
    if ($PSCmdlet.ShouldProcess($Venv, 'Create the venv')) {
        Invoke-Checked $exe ($lead + @('-m', 'venv', $Venv))
    }
}

Step '2/4 Python packages'
if ($PSCmdlet.ShouldProcess($Venv, "pip install -r $($Requirements -join ' -r ')")) {
    $arguments = @('-m', 'pip', 'install', '--disable-pip-version-check')
    foreach ($file in $Requirements) { $arguments += @('-r', $file) }
    Invoke-Checked $VenvPython $arguments
}

Step '3/4 MexCLI and HSDRawViewer'
if ($SkipNative) {
    Write-Host 'Skipped (-SkipNative).'
} elseif ($PSCmdlet.ShouldProcess((Join-Path $Root 'app\utility'), 'Fetch the pinned native tools (tools\build\fetch_native.py all)')) {
    # Public releases download with no login; a private fork needs `gh auth login` or NUCLEUS_FETCH_TOKEN.
    Invoke-Checked $VenvPython @((Join-Path $Root 'tools\build\fetch_native.py'), 'all')
}

Step '4/4 .NET SDK (stage_workbench)'
$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
$sdks = if ($dotnet) { & dotnet --list-sdks 2>$null } else { $null }
if ($sdks) {
    Write-Host "Found the .NET SDK: $(@($sdks)[-1])"
} else {
    Write-Host 'The .NET SDK was not found. native_port works without it; stage_workbench needs it to build its stage' -ForegroundColor Yellow
    Write-Host 'tool. Install it from https://dotnet.microsoft.com/download, then restart SSBM Nucleus.' -ForegroundColor Yellow
}

Write-Host "`nSource games are your own: the toolkit reads the games you installed, and never downloads one."
if ($WhatIfPreference) {
    Write-Host "`nDry run (-WhatIf): nothing was changed."
} else {
    Write-Host "`nDone. Tell your AI to call connect_creation_toolkit with:" -ForegroundColor Green
    Write-Host "  {`"path`": `"$($Root -replace '\\', '/')`"}"
}
