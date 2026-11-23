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
$tempShortcut = $null
try {
    $release = Join-Path (Join-Path $root 'releases') $Version
    $shortcut = Join-Path $root 'Posture Monitor.lnk'
    $shell = New-Object -ComObject WScript.Shell
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
        if (Test-Path -LiteralPath $shortcut) {
            $previous = Split-Path ($shell.CreateShortcut($shortcut).TargetPath)
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
    $tempShortcut = Join-Path $root ("switch-" + [guid]::NewGuid() + '.lnk')
    $link = $shell.CreateShortcut($tempShortcut)
    $link.TargetPath = $target
    $link.WorkingDirectory = $working
    $link.Save()
    if ([IO.File]::Exists($shortcut)) {
        $backup = Join-Path $root ("previous-" + [guid]::NewGuid() + '.lnk')
        [IO.File]::Replace($tempShortcut, $shortcut, $backup)
        [IO.File]::Delete($backup)
    } else { [IO.File]::Move($tempShortcut, $shortcut) }
    Write-Output $shortcut
} finally {
    if ($staging -and (Test-Path -LiteralPath $staging)) { Remove-Item -LiteralPath $staging -Recurse -Force }
    if ($tempShortcut -and [IO.File]::Exists($tempShortcut)) { [IO.File]::Delete($tempShortcut) }
    $lock.Dispose()
}
