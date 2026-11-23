param([Parameter(Mandatory)][string]$Package)
$ErrorActionPreference = 'Stop'
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
$shell = New-Object -ComObject WScript.Shell
function Check-Version([string]$expected) {
    $shortcut = $shell.CreateShortcut((Join-Path $root 'Posture Monitor.lnk'))
    $release = Join-Path (Join-Path $root 'releases') $expected
    if ($shortcut.TargetPath -ne (Join-Path $release 'PostureMonitor.exe')) { throw 'Incorrect active release.' }
    if ($shortcut.WorkingDirectory -ne $data) { throw 'Incorrect working directory.' }
    if ([IO.File]::ReadAllText((Join-Path $release 'posture-data.path')).Trim() -ne $data) { throw 'Incorrect runtime data path.' }
    $process = Start-Process -FilePath $shortcut.TargetPath -WorkingDirectory $data -PassThru
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
