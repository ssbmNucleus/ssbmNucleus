<#
Stops THIS checkout's stale dev processes before tools/build/start.bat starts new
ones. By PID only, never by image name: node.exe and python.exe also run unrelated
apps on this machine, among them the host app agent sessions run in, and an
image-wide kill takes those down too.

A process is stopped only when it belongs to this checkout and is one of what
start.bat starts:
  - the backend: python running app.py with this checkout's venv or app\backend
    path on its command line, or this checkout's built mex_backend.exe
  - the Vite dev server and the Electron launcher: node running this checkout's
    app\...\node_modules\vite\ or \electron\
  - Electron itself: electron.exe from this checkout's app\node_modules\
Listeners on the backend's preferred port (5000) and the Vite port (3000, or the
one in app\frontend\.vite-port) are stopped only when they, or a parent, pass the
same test; anyone else's listener is reported and left alone.
Never stopped: this script and its parents, anything whose parent chain reaches
o3code, cargo or tauri (the host app), and whatever holds port 1420 (the host's).

  powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\stop_stale_dev.ps1 [-DryRun]
#>
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path.TrimEnd('\')
$appDir = "$repo\app\"

$procs = @{}
foreach ($p in Get-CimInstance Win32_Process) { $procs[[int]$p.ProcessId] = $p }

function Get-Chain([int]$id) {
    # the process and its ancestors, nearest first
    $chain = @()
    $seen = @{}
    while ($procs.ContainsKey($id) -and -not $seen.ContainsKey($id)) {
        $seen[$id] = $true
        $chain += $procs[$id]
        $id = [int]$procs[$id].ParentProcessId
    }
    return $chain
}

function Test-Host($p) {
    foreach ($a in Get-Chain ([int]$p.ProcessId)) {
        if ($a.Name -match '^(o3code|cargo|tauri)' -or "$($a.CommandLine)" -like '*o3code*') { return $true }
    }
    return $false
}

function Test-Ours($p) {
    $cmd = "$($p.CommandLine)"
    $exe = "$($p.ExecutablePath)"
    $name = "$($p.Name)".ToLowerInvariant()
    if ($name -eq 'python.exe' -or $name -eq 'pythonw.exe') {
        $mine = ($exe -like "$appDir*") -or ($cmd -like "*$appDir*")
        return $mine -and ($cmd -match '(?<![\w.-])app\.py\b')
    }
    if ($name -eq 'mex_backend.exe' -or $name -eq 'mex_backend') { return $exe -like "$repo\*" }
    if ($name -eq 'node.exe') { return ($cmd -like "*$appDir*") -and ($cmd -match '(?i)\\node_modules\\(vite|electron)\\') }
    if ($name -eq 'electron.exe') { return $exe -like "${appDir}node_modules\*" }
    return $false
}

$protected = @{}
foreach ($a in Get-Chain $PID) { $protected[[int]$a.ProcessId] = $true }

$targets = @{}
foreach ($p in $procs.Values) {
    if (Test-Ours $p) { $targets[[int]$p.ProcessId] = $p }
}

$ports = @(5000, 3000)
$vitePortFile = Join-Path $repo 'app\frontend\.vite-port'
if (Test-Path $vitePortFile) {
    $vitePort = (Get-Content $vitePortFile -Raw).Trim()
    if ($vitePort -match '^\d+$') { $ports += [int]$vitePort }
}
foreach ($port in ($ports | Select-Object -Unique)) {
    if ($port -eq 1420) { continue }
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    foreach ($owner in ($listeners | ForEach-Object { [int]$_.OwningProcess } | Select-Object -Unique)) {
        $ours = Get-Chain $owner | Where-Object { Test-Ours $_ } | Select-Object -First 1
        if ($ours) {
            $targets[[int]$ours.ProcessId] = $ours
        } elseif ($procs.ContainsKey($owner)) {
            Write-Host "  port $port is held by PID $owner ($($procs[$owner].Name)), not this checkout's: left alone"
        }
    }
}

foreach ($p in $targets.Values) {
    $id = [int]$p.ProcessId
    if ($protected.ContainsKey($id)) { continue }
    if (Test-Host $p) {
        Write-Host "  PID $id ($($p.Name)) runs under the host app's process tree: left alone"
        continue
    }
    if ($DryRun) {
        Write-Host "  would stop PID $id $($p.Name): $($p.CommandLine)"
        continue
    }
    Write-Host "  stopping PID $id $($p.Name)"
    # through cmd so a PID already gone with its parent's tree is not a PowerShell error
    & cmd.exe /d /c "taskkill /PID $id /T /F >nul 2>&1"
}
