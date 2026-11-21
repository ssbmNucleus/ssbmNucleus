param(
    [Parameter(Mandatory = $true)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [ValidateSet('focus', 'tap', 'keyDown', 'keyUp')]
    [string]$Action,

    [string]$Key,

    [int]$DurationMs = 80,

    [int]$FocusTimeoutMs = 10000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class DolphinInputNative
{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

    [DllImport("user32.dll")]
    public static extern uint MapVirtualKey(uint uCode, uint uMapType);
}
"@

function Resolve-VirtualKey {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $normalized = $Name.Trim().ToUpperInvariant()
    $map = @{
        'ENTER'  = 0x0D
        'RETURN' = 0x0D
        'ESC'    = 0x1B
        'ESCAPE' = 0x1B
        'SPACE'  = 0x20
        'LEFT'   = 0x25
        'UP'     = 0x26
        'RIGHT'  = 0x27
        'DOWN'   = 0x28
        'LSHIFT' = 0xA0
        'LCTRL'  = 0xA2
        'LCONTROL' = 0xA2
        'LMENU'  = 0xA4
    }

    if ($map.ContainsKey($normalized)) {
        return [byte]$map[$normalized]
    }

    if ($normalized.Length -eq 1) {
        $charCode = [int][char]$normalized
        return [byte]$charCode
    }

    throw "Unsupported key name: $Name"
}

function Get-MainWindowHandle {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TargetPid,

        [Parameter(Mandatory = $true)]
        [int]$TimeoutMs
    )

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)

    while ([DateTime]::UtcNow -lt $deadline) {
        $process = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
        if (-not $process) {
            throw "Process $TargetPid is no longer running."
        }

        if ($process.MainWindowHandle -ne 0) {
            return $process.MainWindowHandle
        }

        Start-Sleep -Milliseconds 200
    }

    throw "Timed out waiting for process $TargetPid to create a window."
}

function Focus-Window {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TargetPid,

        [Parameter(Mandatory = $true)]
        [int]$TimeoutMs
    )

    $handle = Get-MainWindowHandle -TargetPid $TargetPid -TimeoutMs $TimeoutMs
    [void][DolphinInputNative]::ShowWindowAsync($handle, 5)
    Start-Sleep -Milliseconds 100

    $focused = [DolphinInputNative]::SetForegroundWindow($handle)
    if (-not $focused) {
        try {
            $shell = New-Object -ComObject WScript.Shell
            $focused = $shell.AppActivate($TargetPid)
        }
        catch {
            $focused = $false
        }
    }

    if (-not $focused) {
        throw "Failed to focus Dolphin window for process $TargetPid."
    }

    Start-Sleep -Milliseconds 100
}

function Send-KeyEvent {
    param(
        [Parameter(Mandatory = $true)]
        [byte]$VirtualKey,

        [Parameter(Mandatory = $true)]
        [bool]$KeyUp
    )

    # Dolphin's "DInput/0/Keyboard Mouse" device reads hardware SCAN CODES, not
    # virtual keys. Injecting VK events with scan code 0 (the old behavior) is
    # frequently invisible to DirectInput, so emit the real scan code with
    # KEYEVENTF_SCANCODE. Arrow keys (and a handful of others) are "extended"
    # keys that also need KEYEVENTF_EXTENDEDKEY or DInput reads them as the
    # numpad equivalents. This is what makes background input actually land.
    $KEYEVENTF_EXTENDEDKEY = 0x0001
    $KEYEVENTF_KEYUP       = 0x0002
    $KEYEVENTF_SCANCODE    = 0x0008

    $scan = [DolphinInputNative]::MapVirtualKey([uint32]$VirtualKey, 0)  # MAPVK_VK_TO_VSC

    $extendedKeys = @(0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x90, 0xA3, 0xA5)
    $flags = $KEYEVENTF_SCANCODE
    if ($extendedKeys -contains [int]$VirtualKey) { $flags = $flags -bor $KEYEVENTF_EXTENDEDKEY }
    if ($KeyUp) { $flags = $flags -bor $KEYEVENTF_KEYUP }

    [DolphinInputNative]::keybd_event($VirtualKey, [byte]$scan, $flags, [UIntPtr]::Zero)
}

if ($Action -eq 'focus') {
    Focus-Window -TargetPid $ProcessId -TimeoutMs $FocusTimeoutMs
    exit 0
}

if (-not $Key) {
    throw "A key is required for action '$Action'."
}

$virtualKey = Resolve-VirtualKey -Name $Key
Focus-Window -TargetPid $ProcessId -TimeoutMs $FocusTimeoutMs

switch ($Action) {
    'tap' {
        Send-KeyEvent -VirtualKey $virtualKey -KeyUp $false
        Start-Sleep -Milliseconds $DurationMs
        Send-KeyEvent -VirtualKey $virtualKey -KeyUp $true
    }
    'keyDown' {
        Send-KeyEvent -VirtualKey $virtualKey -KeyUp $false
    }
    'keyUp' {
        Send-KeyEvent -VirtualKey $virtualKey -KeyUp $true
    }
}
