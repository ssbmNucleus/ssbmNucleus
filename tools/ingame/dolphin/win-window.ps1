param(
    [Parameter(Mandatory = $true)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [ValidateSet('capture', 'title')]
    [string]$Action,

    [string]$OutputPath,

    [int]$TimeoutMs = 10000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class DolphinWindowNative
{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
}
"@

function Get-TargetProcess {
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
            return $process
        }

        Start-Sleep -Milliseconds 200
    }

    throw "Timed out waiting for process $TargetPid to create a window."
}

function Focus-ProcessWindow {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process
    )

    [void][DolphinWindowNative]::ShowWindowAsync($Process.MainWindowHandle, 5)
    Start-Sleep -Milliseconds 100

    $focused = [DolphinWindowNative]::SetForegroundWindow($Process.MainWindowHandle)
    if (-not $focused) {
        try {
            $shell = New-Object -ComObject WScript.Shell
            $focused = $shell.AppActivate($Process.Id)
        }
        catch {
            $focused = $false
        }
    }

    Start-Sleep -Milliseconds 150
}

function Get-WindowRectForProcess {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process
    )

    $rect = New-Object DolphinWindowNative+RECT
    $ok = [DolphinWindowNative]::GetWindowRect($Process.MainWindowHandle, [ref]$rect)
    if (-not $ok) {
        throw "Failed to read window rectangle for process $($Process.Id)."
    }

    return $rect
}

function Test-BitmapHasVisibleInterior {
    param(
        [Parameter(Mandatory = $true)]
        [System.Drawing.Bitmap]$Bitmap
    )

    if ($Bitmap.Width -lt 40 -or $Bitmap.Height -lt 80) {
        return $false
    }

    $startX = [Math]::Max(10, [int]($Bitmap.Width * 0.10))
    $endX = [Math]::Min($Bitmap.Width - 10, [int]($Bitmap.Width * 0.90))
    $startY = [Math]::Max(60, [int]($Bitmap.Height * 0.20))
    $endY = [Math]::Min($Bitmap.Height - 10, [int]($Bitmap.Height * 0.90))

    $samplesX = 6
    $samplesY = 6

    for ($xi = 0; $xi -lt $samplesX; $xi++) {
        for ($yi = 0; $yi -lt $samplesY; $yi++) {
            $x = [int]($startX + (($endX - $startX) * $xi / [Math]::Max(1, $samplesX - 1)))
            $y = [int]($startY + (($endY - $startY) * $yi / [Math]::Max(1, $samplesY - 1)))
            $pixel = $Bitmap.GetPixel($x, $y)
            if (($pixel.R + $pixel.G + $pixel.B) -gt 24) {
                return $true
            }
        }
    }

    return $false
}

$process = Get-TargetProcess -TargetPid $ProcessId -TimeoutMs $TimeoutMs

if ($Action -eq 'title') {
    Write-Output $process.MainWindowTitle
    exit 0
}

if (-not $OutputPath) {
    throw "OutputPath is required when Action is 'capture'."
}

Focus-ProcessWindow -Process $process
$rect = Get-WindowRectForProcess -Process $process
$width = [Math]::Max(1, $rect.Right - $rect.Left)
$height = [Math]::Max(1, $rect.Bottom - $rect.Top)

$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)

try {
    $hdc = $graphics.GetHdc()
    try {
        $captured = [DolphinWindowNative]::PrintWindow($process.MainWindowHandle, $hdc, 2)
    }
    finally {
        $graphics.ReleaseHdc($hdc)
    }

    if ((-not $captured) -or (-not (Test-BitmapHasVisibleInterior -Bitmap $bitmap))) {
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
    }

    $directory = Split-Path -Parent $OutputPath
    if ($directory) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Output $OutputPath
}
finally {
    $graphics.Dispose()
    $bitmap.Dispose()
}
