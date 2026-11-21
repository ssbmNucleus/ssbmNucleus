param(
    [Parameter(Mandatory = $true)]
    [int]$ProcessId,

    # Comma-separated key names to tap in order (e.g. "DOWN,DOWN,X"). May be empty
    # for a screenshot-only call.
    [string]$Keys = "",

    [int]$DurationMs = 90,
    [int]$GapMs = 110,

    # When set, capture the window to this PNG after sending the keys.
    [string]$OutputPath = "",

    [int]$FocusTimeoutMs = 10000
)

# Fast path for the interactive control loop: does focus + all key taps + a
# screenshot in ONE PowerShell process, and compiles the P/Invoke surface once
# into a cached DLL so subsequent calls skip the (~1.5s) Add-Type compile. The
# per-input win-input.ps1 / win-window.ps1 helpers are unchanged and still used
# by the driver scenarios.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

$nativeCode = @"
using System;
using System.Runtime.InteropServices;

public static class DolphinBatchNative
{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint uCode, uint uMapType);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
}
"@

# Compile once, cache as a DLL, then load the cached assembly on later calls.
$cacheDll = Join-Path ([System.IO.Path]::GetTempPath()) 'DolphinBatchNative.dll'
if (-not ('DolphinBatchNative' -as [type])) {
    if (Test-Path -LiteralPath $cacheDll) {
        Add-Type -Path $cacheDll
    } else {
        Add-Type -TypeDefinition $nativeCode -OutputAssembly $cacheDll
        Add-Type -Path $cacheDll
    }
}

function Resolve-VirtualKey {
    param([string]$Name)
    $normalized = $Name.Trim().ToUpperInvariant()
    $map = @{
        'ENTER' = 0x0D; 'RETURN' = 0x0D; 'ESC' = 0x1B; 'ESCAPE' = 0x1B; 'SPACE' = 0x20
        'LEFT' = 0x25; 'UP' = 0x26; 'RIGHT' = 0x27; 'DOWN' = 0x28
        'LSHIFT' = 0xA0; 'LCTRL' = 0xA2; 'LCONTROL' = 0xA2; 'LMENU' = 0xA4
    }
    if ($map.ContainsKey($normalized)) { return [byte]$map[$normalized] }
    if ($normalized.Length -eq 1) { return [byte][int][char]$normalized }
    throw "Unsupported key name: $Name"
}

function Get-TargetProcess {
    param([int]$TargetPid, [int]$TimeoutMs)
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    while ([DateTime]::UtcNow -lt $deadline) {
        $p = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
        if (-not $p) { throw "Process $TargetPid is no longer running." }
        if ($p.MainWindowHandle -ne 0) { return $p }
        Start-Sleep -Milliseconds 150
    }
    throw "Timed out waiting for process $TargetPid to create a window."
}

function Focus-Window {
    param([IntPtr]$Handle, [int]$TargetPid)
    [void][DolphinBatchNative]::ShowWindowAsync($Handle, 5)
    Start-Sleep -Milliseconds 60
    $ok = [DolphinBatchNative]::SetForegroundWindow($Handle)
    if (-not $ok) {
        try { (New-Object -ComObject WScript.Shell).AppActivate($TargetPid) | Out-Null } catch { }
    }
    Start-Sleep -Milliseconds 60
}

function Send-Key {
    param([byte]$Vk, [int]$HoldMs)
    $KEYEVENTF_EXTENDEDKEY = 0x0001
    $KEYEVENTF_KEYUP = 0x0002
    $KEYEVENTF_SCANCODE = 0x0008
    $scan = [DolphinBatchNative]::MapVirtualKey([uint32]$Vk, 0)
    $extended = @(0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x90, 0xA3, 0xA5)
    $down = $KEYEVENTF_SCANCODE
    if ($extended -contains [int]$Vk) { $down = $down -bor $KEYEVENTF_EXTENDEDKEY }
    [DolphinBatchNative]::keybd_event($Vk, [byte]$scan, $down, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds $HoldMs
    [DolphinBatchNative]::keybd_event($Vk, [byte]$scan, ($down -bor $KEYEVENTF_KEYUP), [UIntPtr]::Zero)
}

$process = Get-TargetProcess -TargetPid $ProcessId -TimeoutMs $FocusTimeoutMs
$handle = $process.MainWindowHandle
Focus-Window -Handle $handle -TargetPid $ProcessId

# Keys is a comma-separated list. Each item is "NAME" (uses -DurationMs) or
# "NAME:HOLDMS" for a per-key hold, e.g. "LEFT:450,UP:450,DOWN,DOWN,RIGHT,X:60".
# A per-key hold lets one process both pin the cursor to a wall (long hold) and
# step single cells (short taps) -- the whole CSS navigation in one shot.
if ($Keys.Trim()) {
    $items = $Keys.Split(',') | Where-Object { $_.Trim() }
    foreach ($item in $items) {
        $parts = $item.Trim().Split(':')
        $name = $parts[0].Trim()
        $hold = if ($parts.Count -gt 1 -and $parts[1].Trim()) { [int]$parts[1] } else { $DurationMs }
        Send-Key -Vk (Resolve-VirtualKey $name) -HoldMs $hold
        Start-Sleep -Milliseconds $GapMs
    }
}

if ($OutputPath) {
    $rect = New-Object DolphinBatchNative+RECT
    [void][DolphinBatchNative]::GetWindowRect($handle, [ref]$rect)
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $hdc = $graphics.GetHdc()
        try { $ok = [DolphinBatchNative]::PrintWindow($handle, $hdc, 2) } finally { $graphics.ReleaseHdc($hdc) }
        if (-not $ok) { $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size) }
        $dir = Split-Path -Parent $OutputPath
        if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
        Write-Output $OutputPath
    } finally {
        $graphics.Dispose(); $bitmap.Dispose()
    }
}
