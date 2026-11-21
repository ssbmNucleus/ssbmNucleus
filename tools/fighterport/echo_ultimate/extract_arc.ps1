param(
    [Parameter(Mandatory=$true)][string]$ArcPath,
    [Parameter(Mandatory=$true)][string]$FileList,
    [Parameter(Mandatory=$true)][string]$NativeLibrary,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [uint32]$Region = 2
)
# Targeted extraction through the native library distributed with ArcExplorer.
# Inputs are a decrypted data.arc and an explicit UTF-8 list of archive paths.
# This command never needs console keys. Existing output files are refused.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$arcFile = Get-Item -LiteralPath $ArcPath
$libraryFile = Get-Item -LiteralPath $NativeLibrary
$listFile = Get-Item -LiteralPath $FileList
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\','/')
# Get-Content decorates strings with provider/drive objects. Serializing those
# under files[].path in PowerShell 5 can recursively expand gigabytes of state.
$paths = @([IO.File]::ReadAllLines($listFile.FullName) | Where-Object { $_.Trim() } | Sort-Object -Unique)
if($paths.Count -eq 0) { throw 'The archive path list is empty.' }
$targets = @{}
foreach($path in $paths) {
    if([IO.Path]::IsPathRooted($path) -or $path.Contains(':')) { throw "Invalid archive path: $path" }
    $target = [IO.Path]::GetFullPath((Join-Path $outputRoot $path))
    if(-not $target.StartsWith($outputRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw "Path escapes output directory: $path" }
    if(Test-Path -LiteralPath $target) { throw "Output already exists: $target" }
    $targets[$path] = $target
}
if(Test-Path -LiteralPath (Join-Path $outputRoot 'extraction.json')) { throw 'Output manifest already exists.' }
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ArcNative {
    [StructLayout(LayoutKind.Sequential)] public struct Hash40 { public ulong Value; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr LoadLibrary(string path);
    [DllImport("smash_arc.dll", CallingConvention=CallingConvention.Cdecl)]
    public static extern IntPtr arc_open([MarshalAs(UnmanagedType.LPUTF8Str)] string path);
    [DllImport("smash_arc.dll", CallingConvention=CallingConvention.Cdecl)]
    public static extern void arc_free(IntPtr arc);
    [DllImport("smash_arc.dll", CallingConvention=CallingConvention.Cdecl)]
    public static extern Hash40 arc_str_to_hash40([MarshalAs(UnmanagedType.LPUTF8Str)] string path);
    [DllImport("smash_arc.dll", CallingConvention=CallingConvention.Cdecl)]
    public static extern uint arc_get_version(IntPtr arc);
    [DllImport("smash_arc.dll", CallingConvention=CallingConvention.Cdecl)]
    public static extern byte arc_extract_file_regional(IntPtr arc, Hash40 hash,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string output, uint region);
}
'@
if([ArcNative]::LoadLibrary($libraryFile.FullName) -eq [IntPtr]::Zero) {
    throw ('Cannot load native library; Win32 error '+[Runtime.InteropServices.Marshal]::GetLastWin32Error())
}
$arc = [ArcNative]::arc_open($arcFile.FullName)
if($arc -eq [IntPtr]::Zero) { throw 'The archive library could not open data.arc.' }
$results = @()
try {
    $version = [ArcNative]::arc_get_version($arc)
    foreach($path in $paths) {
        $target = $targets[$path]
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
        $hash = [ArcNative]::arc_str_to_hash40($path)
        $result = [ArcNative]::arc_extract_file_regional($arc,$hash,$target,$Region)
        if($result -eq 0) {
            $item = Get-Item -LiteralPath $target
            $results += @{path=$path;status='ok';bytes=$item.Length;sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
        } elseif($result -eq 2) {
            $results += @{path=$path;status='missing'}
        } else {
            throw "Archive extraction failed ($result): $path"
        }
    }
} finally {
    [ArcNative]::arc_free($arc)
}
Write-Output ('Extracted '+$results.Count+' paths; hashing source archive')
$manifest = @{schema=1;archive=@{path=$arcFile.FullName;bytes=$arcFile.Length;version=$version;
    sha256=(Get-FileHash -LiteralPath $arcFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()};
    native_library=@{path=$libraryFile.FullName;sha256=(Get-FileHash -LiteralPath $libraryFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()};
    file_list_sha256=(Get-FileHash -LiteralPath $listFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant();
    region=$Region;files=$results}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$manifest | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $outputRoot 'extraction.json') -Encoding UTF8
@{files=$results.Count;extracted=@($results | Where-Object {$_.status -eq 'ok'}).Count;missing=@($results | Where-Object {$_.status -eq 'missing'}).Count;output=$outputRoot} | ConvertTo-Json -Compress
