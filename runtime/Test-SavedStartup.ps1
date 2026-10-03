[CmdletBinding()]
param([string]$LaunchFile, [switch]$Live)
$ErrorActionPreference = 'Stop'
if (-not $LaunchFile) { $LaunchFile = Join-Path $PSScriptRoot 'Open-Heretic.ps1' }
foreach ($file in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1') {
    $tokens = $null
    $errors = $null
    [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors) { throw ($errors | Out-String) }
}
Write-Output 'PowerShell syntax: PASS'
foreach ($name in @('Start-Heretic.ps1', 'Open-Heretic.ps1')) {
    $script = Get-Content -LiteralPath (Join-Path $PSScriptRoot $name) -Raw
    $listeners = @($script -split "`n" | Where-Object { $_ -match 'Get-NetTCPConnection' })
    if (-not $listeners -or @($listeners | Where-Object { $_ -notmatch 'Where-Object.*LocalAddress.*127\.0\.0\.1' }).Count) { throw "Loopback listener filtering missing in $name" }
}
$addresses = @('127.0.0.1', '0.0.0.0', '::', '100.91.115.41', 'fd7a:115c:a1e0::1')
$local = @($addresses | Where-Object { $_ -in @('127.0.0.1', '0.0.0.0', '::') })
if ($local.Count -ne 3 -or $local -contains '100.91.115.41' -or $local -contains 'fd7a:115c:a1e0::1') { throw 'Tailscale listener exclusion fixture failed.' }
Write-Output 'Loopback filtering excludes Tailscale Serve listeners: PASS'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('heretic-startup-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture | Out-Null
$fixtureCleanupSafe = $true
try {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Stop-Heretic.ps1') -Destination $fixture
    $self = Get-Process -Id $PID
    [pscustomobject]@{ Version = 1; Processes = @([pscustomobject]@{ Name = 'fixture'; Pid = $PID; Executable = $self.Path; StartedUtc = $self.StartTime.ToUniversalTime().ToString('o') }) } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $fixture 'heretic-processes.json') -Encoding UTF8
    $validated = & (Join-Path $fixture 'Stop-Heretic.ps1') -ValidateOnly
    if ($validated.Id -ne $PID) { throw 'Valid owned process fixture was not accepted.' }
    $record = Get-Content -LiteralPath (Join-Path $fixture 'heretic-processes.json') -Raw | ConvertFrom-Json
    $record.Processes[0].StartedUtc = [DateTime]::UtcNow.AddDays(-1).ToString('o')
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $fixture 'heretic-processes.json') -Encoding UTF8
    $rejected = $false
    try { & (Join-Path $fixture 'Stop-Heretic.ps1') -ValidateOnly | Out-Null } catch {
        if ($_.Exception.Message -notlike 'Process identity mismatch*') { throw }
        $rejected = $true
    }
    if (-not $rejected) { throw 'PID reuse fixture was accepted.' }
    Write-Output 'Owned process identity and PID reuse rejection: PASS'
    $source = Join-Path $fixture 'source'
    $destination = Join-Path $fixture 'installed'
    foreach ($directory in @('runtime', 'gateway\heretic_gateway', 'ui\dist')) { New-Item -ItemType Directory -Path (Join-Path $source $directory) -Force | Out-Null }
    New-Item -ItemType Directory -Path $destination | Out-Null
    foreach ($name in @('Start-Heretic.ps1', 'Open-Heretic.ps1', 'Stop-Heretic.ps1', 'Test-SavedStartup.ps1', 'README-Heretic.md', 'Install-Gateway.ps1')) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $source "runtime\$name") }
    foreach ($name in @('pyproject.toml', 'uv.lock')) { 'fixture' | Set-Content -LiteralPath (Join-Path $source "gateway\$name") }
    'fixture' | Set-Content -LiteralPath (Join-Path $source 'gateway\heretic_gateway\__init__.py')
    'fixture UI' | Set-Content -LiteralPath (Join-Path $source 'ui\dist\index.html')
    'original launcher' | Set-Content -LiteralPath (Join-Path $destination 'Open-Heretic.ps1')
    'personal data' | Set-Content -LiteralPath (Join-Path $destination 'personal-data.txt')
    'original MCP config' | Set-Content -LiteralPath (Join-Path $destination 'heretic.mcp.json')
    function uv { $global:LASTEXITCODE = 0 }
    & (Join-Path $PSScriptRoot 'Install-Gateway.ps1') -RepositoryRoot $source -RuntimePath $destination | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $destination 'gateway\heretic_gateway\__init__.py')) -or -not (Test-Path -LiteralPath (Join-Path $destination 'ui\index.html'))) { throw 'Fixture install did not copy package and UI.' }
    $backup = (Get-ChildItem -LiteralPath (Join-Path $destination 'saved-setup') -Directory)[0].FullName
    & (Join-Path $PSScriptRoot 'Install-Gateway.ps1') -RuntimePath $destination -RollbackBackup $backup | Out-Null
    if ((Get-Content -LiteralPath (Join-Path $destination 'Open-Heretic.ps1') -Raw).Trim() -ne 'original launcher') { throw 'Rollback did not restore the original launcher.' }
    if ((Get-Content -LiteralPath (Join-Path $destination 'personal-data.txt') -Raw).Trim() -ne 'personal data' -or (Get-Content -LiteralPath (Join-Path $destination 'heretic.mcp.json') -Raw).Trim() -ne 'original MCP config') { throw 'Install or rollback changed personal data or MCP config.' }
    Write-Output 'Install backup, package/UI copy, rollback and personal data preservation (mock uv): PASS'
    $python = Join-Path (Split-Path $PSScriptRoot -Parent) 'gateway\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = Join-Path $PSScriptRoot 'gateway\.venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'The real venv ownership fixture requires gateway/.venv/Scripts/python.exe.' }
    $runtimeDir = Join-Path $fixture 'http-runtime'
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Stop-Heretic.ps1') -Destination $runtimeDir
    'owned fixture' | Set-Content -LiteralPath (Join-Path $runtimeDir 'index.html')
    $pidFile = Join-Path $runtimeDir 'heretic-processes.json'
    $records = New-Object System.Collections.Generic.List[object]
    foreach ($scriptName in @('Start-Heretic.ps1', 'Open-Heretic.ps1')) {
        $functionTokens = $null
        $functionErrors = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $scriptName), [ref]$functionTokens, [ref]$functionErrors)
        foreach ($definition in $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
            if ($definition.Name -in @('Save-OwnedRecords', 'Update-OwnedChildren', 'Start-OwnedProcess', 'Test-OwnedGatewayListener')) { Invoke-Expression $definition.Extent.Text }
        }
    }
    $reservation = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    $reservation.Start()
    $fixturePort = $reservation.LocalEndpoint.Port
    $reservation.Stop()
    $httpProcess = $null
    try {
        $healthScript = Join-Path $runtimeDir 'slow-health.py'
        @'
import http.server, sys, time
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(2)
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'owned fixture')
http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
'@ | Set-Content -LiteralPath $healthScript -Encoding UTF8
        $httpProcess = Start-OwnedProcess 'gateway' $python @('"' + $healthScript + '"', [string]$fixturePort) $runtimeDir
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            try { $ready = (Invoke-WebRequest "http://127.0.0.1:$fixturePort/" -UseBasicParsing -TimeoutSec 6).Content.Trim() -eq 'owned fixture' } catch { }
            if ($ready) { break }
            Start-Sleep -Milliseconds 100
        }
        if (-not $ready) { throw 'Real venv HTTP fixture failed to start.' }
        $record = Update-OwnedChildren 'gateway'
        $listener = @(Get-NetTCPConnection -LocalPort $fixturePort -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -eq '127.0.0.1' })
        $ownedIds = @($record.Pid) + @($record.Children | ForEach-Object Pid)
        if (-not $listener -or $listener[0].OwningProcess -notin $ownedIds) { throw 'Fixture HTTP socket was not owned by the launcher tree.' }
        $record.EffectivePid = $listener[0].OwningProcess
        if ($record.EffectivePid -eq $record.Pid -or -not $record.Children.Count) { throw 'Fixture did not exercise the Windows venv redirector child.' }
        Save-OwnedRecords
        Test-OwnedGatewayListener $listener $record
        $validated = @(& (Join-Path $runtimeDir 'Stop-Heretic.ps1') -ValidateOnly)
        if ($record.Pid -notin $validated.Id -or $record.EffectivePid -notin $validated.Id) { throw 'Launcher and actual HTTP child were not both validated.' }
        & (Join-Path $runtimeDir 'Stop-Heretic.ps1') | Out-Null
        foreach ($ownedId in $ownedIds) {
            if (Get-Process -Id $ownedId -ErrorAction SilentlyContinue) { throw "Fixture process $ownedId survived stop." }
        }
        if (Test-Path -LiteralPath $pidFile) { throw 'Successful fixture cleanup retained ownership records.' }
        Write-Output 'Real Windows venv HTTP start, child listener ownership, reopen validation and complete stop: PASS'
        $records.Clear()
        $workerScript = Join-Path $runtimeDir 'late-worker.py'
        @'
import pathlib, subprocess, sys, time
root = pathlib.Path(__file__).parent
while not (root / 'spawn-late').exists():
    time.sleep(.05)
worker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
(root / 'late-pid').write_text(str(worker.pid))
time.sleep(120)
'@ | Set-Content -LiteralPath $workerScript -Encoding UTF8
        $lateLauncher = Start-OwnedProcess 'gateway' $python @('"' + $workerScript + '"') $runtimeDir
        $record = Update-OwnedChildren 'gateway'
        $snapshotIds = @($record.Pid) + @($record.Children | ForEach-Object Pid)
        Save-OwnedRecords
        New-Item -ItemType File -Path (Join-Path $runtimeDir 'spawn-late') | Out-Null
        for ($attempt = 0; $attempt -lt 60 -and -not (Test-Path -LiteralPath (Join-Path $runtimeDir 'late-pid')); $attempt++) { Start-Sleep -Milliseconds 50 }
        if (-not (Test-Path -LiteralPath (Join-Path $runtimeDir 'late-pid'))) { throw 'Late child fixture did not spawn.' }
        $lateId = [int](Get-Content -LiteralPath (Join-Path $runtimeDir 'late-pid') -Raw)
        if ($lateId -in $snapshotIds) { throw 'Late child was incorrectly present in the startup snapshot.' }
        & (Join-Path $runtimeDir 'Stop-Heretic.ps1') | Out-Null
        foreach ($ownedId in @($snapshotIds) + @($lateId)) {
            if (Get-Process -Id $ownedId -ErrorAction SilentlyContinue) { throw "Late child fixture process $ownedId survived stop." }
        }
        Write-Output 'Real Windows delayed child discovery after saved snapshot and complete tree cleanup: PASS'
    } catch {
        $primaryFailure = $_
        throw
    } finally {
        if (Test-Path -LiteralPath $pidFile) {
            try { & (Join-Path $runtimeDir 'Stop-Heretic.ps1') | Out-Null } catch {
                $fixtureCleanupSafe = $false
                if ($primaryFailure) { Write-Warning $_.Exception.Message } else { throw }
            }
        }
    }
} finally {
    if ($fixtureCleanupSafe) { Remove-Item -LiteralPath $fixture -Recurse -Force } else { Write-Warning "Fixture ownership records preserved at $fixture" }
}
if (-not $Live) { return }
$lock = New-Object System.Threading.Mutex($false, 'Local\HereticSavedStartup')
$held = $lock.WaitOne(1000)
if (-not $held) { $lock.Dispose(); throw 'Cannot acquire test lock' }
try {
    $child = Start-Process 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $LaunchFile + '"'), '-NoBrowser') -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $child.Refresh()
    if ($child.HasExited) { throw 'Concurrent startup exited instead of waiting' }
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
if (-not $child.WaitForExit(130000)) { throw 'Concurrent startup did not complete' }
if ($child.ExitCode -ne 0) { throw "Concurrent startup failed with exit code $($child.ExitCode)" }
Write-Output 'Concurrent startup waits and succeeds: PASS'
