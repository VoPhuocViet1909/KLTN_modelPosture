[CmdletBinding(DefaultParameterSetName='Install')]
param(
    [Parameter(Mandatory,ParameterSetName='Install')][string]$Package,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')][string]$Version,
    [Parameter(Mandatory,ParameterSetName='Activate')][switch]$Activate,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'PostureMonitor'),
    [Parameter(ParameterSetName='Install')][string]$DataDir
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($InstallDir)
[IO.Directory]::CreateDirectory($root) | Out-Null
$lock = [IO.File]::Open((Join-Path $root 'install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$staging = $null
$tempLauncher = $null
try {
    $release = Join-Path (Join-Path $root 'releases') $Version
    $launcher = Join-Path $root 'Posture Monitor.cmd'
    if (Get-Process -Name PostureMonitor -ErrorAction SilentlyContinue) { throw 'Close Posture Monitor before switching versions.' }
    if (!$Activate) {
        $source = (Resolve-Path -LiteralPath $Package).Path
        foreach ($file in @('PostureMonitor.exe','_internal','release-layout-v1')) {
            if (!(Test-Path -LiteralPath (Join-Path $source $file))) { throw "Incomplete release: $file" }
        }
        foreach ($file in @('out','app_config.json','iot_config.json','posture-data.path')) {
            if (Test-Path -LiteralPath (Join-Path $source $file)) { throw "Release contains local data: $file" }
        }
        if (Test-Path -LiteralPath $release) { throw 'Version exists. Use -Activate to switch back to it.' }
        if (Test-Path -LiteralPath $launcher) {
            $marker = [IO.File]::ReadAllLines($launcher)[1]
            if ($marker -notmatch '^rem release ([A-Za-z0-9][A-Za-z0-9_.-]{0,63})$') { throw 'Invalid release marker.' }
            $previous = Join-Path (Join-Path $root 'releases') $Matches[1]
            $currentData = [IO.File]::ReadAllText((Join-Path $previous 'posture-data.path')).Trim()
            if ($DataDir -and [IO.Path]::GetFullPath($DataDir) -ne $currentData) { throw 'Data directory differs from current installation.' }
            $DataDir = $currentData
        }
        if (!$DataDir) { $DataDir = Join-Path $root 'data' }
        $DataDir = [IO.Path]::GetFullPath($DataDir)
        [IO.Directory]::CreateDirectory($DataDir) | Out-Null
        [IO.Directory]::CreateDirectory((Split-Path $release)) | Out-Null
        $staging = Join-Path (Split-Path $release) ([guid]::NewGuid().ToString())
        [IO.Directory]::CreateDirectory($staging) | Out-Null
        foreach ($file in @('PostureMonitor.exe','_internal','release-layout-v1')) {
            Copy-Item -LiteralPath (Join-Path $source $file) -Destination $staging -Recurse
        }
        [IO.File]::WriteAllText((Join-Path $staging 'posture-data.path'), $DataDir)
        [IO.Directory]::Move($staging, $release)
        $staging = $null
    }
    $target = Join-Path $release 'PostureMonitor.exe'
    if (!(Test-Path -LiteralPath $target -PathType Leaf)) { throw 'Version is not installed.' }
    $working = [IO.File]::ReadAllText((Join-Path $release 'posture-data.path')).Trim()
    if (!(Test-Path -LiteralPath $working -PathType Container)) { throw 'User data directory is unavailable.' }
    $tempLauncher = Join-Path $root ("switch-" + [guid]::NewGuid() + '.cmd')
    $lines = @('@echo off', "rem release $Version", 'setlocal DisableDelayedExpansion',
               ('start "" "%~dp0releases\' + $Version + '\PostureMonitor.exe"'))
    [IO.File]::WriteAllLines($tempLauncher, $lines, [Text.Encoding]::ASCII)
    if ([IO.File]::Exists($launcher)) {
        $backup = Join-Path $root ("previous-" + [guid]::NewGuid() + '.cmd')
        [IO.File]::Replace($tempLauncher, $launcher, $backup)
        [IO.File]::Delete($backup)
    } else { [IO.File]::Move($tempLauncher, $launcher) }
    Write-Output $launcher
} finally {
    if ($staging -and (Test-Path -LiteralPath $staging)) { Remove-Item -LiteralPath $staging -Recurse -Force }
    if ($tempLauncher -and [IO.File]::Exists($tempLauncher)) { [IO.File]::Delete($tempLauncher) }
    $lock.Dispose()
}
