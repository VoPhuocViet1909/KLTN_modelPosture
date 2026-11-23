param([Parameter(Mandatory)][string]$Package)
$ErrorActionPreference = 'Stop'
trap {
    Write-Host $_.ScriptStackTrace
    throw $_
}
$root = Join-Path $env:RUNNER_TEMP ("KLTN thử cài " + [guid]::NewGuid())
$data = Join-Path $root 'dữ liệu'
$out = Join-Path $data 'out'
[IO.Directory]::CreateDirectory($out) | Out-Null
$fixture = Join-Path $out 'outbox.db'
py -3.11 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('create table recovery_fixture(owner text primary key)'); c.execute('insert into recovery_fixture values (?)',('fixture-owner',)); c.commit(); c.close()" $fixture
if ($LASTEXITCODE) { throw 'Cannot prepare SQLite fixture.' }
$config = Join-Path $data 'app_config.json'
[IO.File]::WriteAllText($config, '{}')
$hash = (Get-FileHash $fixture).Hash
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"

function Check-Version([string]$expected) {
    $launcher = Join-Path $root 'Posture Monitor.cmd'
    $release = Join-Path (Join-Path $root 'releases') $expected
    $target = Join-Path $release 'PostureMonitor.exe'
    if ([IO.File]::ReadAllText((Join-Path $release 'posture-data.path')).Trim() -ne $data) { throw 'Incorrect runtime data path.' }
    Start-Process -FilePath $launcher -WorkingDirectory $root
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 250
        $running = Get-Process -Name PostureMonitor -ErrorAction SilentlyContinue | Where-Object Path -eq $target
    } until ($running -or (Get-Date) -gt $deadline)
    $process = $running | Select-Object -First 1
    if (!$process) { throw 'The launcher did not start the expected release.' }
    try {
        $deadline = (Get-Date).AddSeconds(90)
        do {
            Start-Sleep -Milliseconds 500
            $process.Refresh()
            if ($process.HasExited) { throw "Application exited with $($process.ExitCode)." }
        } until (($process.MainWindowHandle -ne 0 -and $process.Responding) -or (Get-Date) -gt $deadline)
        if (!$process.MainWindowHandle -or !$process.Responding) { throw 'GUI did not start.' }
    } finally {
        if (!$process.HasExited) { $process.Kill(); $process.WaitForExit() }
    }
    if ((Get-FileHash $fixture).Hash -ne $hash -or [IO.File]::ReadAllText($config) -ne '{}') { throw 'User fixture changed.' }
}
& "$PSScriptRoot/Install-PostureMonitor.ps1" -InstallDir $root -DataDir $data -Version A -Package $Package
Check-Version A
& "$PSScriptRoot/Install-PostureMonitor.ps1" -InstallDir $root -Version B -Package $Package
Check-Version B
& "$PSScriptRoot/Install-PostureMonitor.ps1" -InstallDir $root -Activate -Version A
Check-Version A
