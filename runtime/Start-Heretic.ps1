[CmdletBinding()]
param([ValidateSet(8192, 65536, 98304, 131072)][int]$ContextSize = 65536, [switch]$WithoutTools)
$ErrorActionPreference = 'Stop'
$mutex = New-Object System.Threading.Mutex($false, 'Local\HereticSavedStartup')
$hasLock = $false
try {
    try { $hasLock = $mutex.WaitOne(120000) } catch [Threading.AbandonedMutexException] { $hasLock = $true }
    if (-not $hasLock) { throw 'Another Heretic startup did not finish within two minutes.' }
    $runtimeDir = $PSScriptRoot
    $serverExe = Join-Path $runtimeDir 'bin\llama-server.exe'
    $modelFile = 'C:\Users\PC\.lmstudio\models\OS-Software\Ternary-Bonsai-2-27B-Uncensored-Heretic-GGUF\Ternary-Bonsai-2-27B-Uncensored-Heretic-PQ2_0.gguf'
    $mcpFile = Join-Path $runtimeDir 'heretic.mcp.json'
    $gatewayDir = Join-Path $runtimeDir 'gateway'
    $gatewayExe = Join-Path $gatewayDir '.venv\Scripts\python.exe'
    $pidFile = Join-Path $runtimeDir 'heretic-processes.json'
    foreach ($required in @($serverExe, $modelFile, $gatewayExe, (Join-Path $runtimeDir 'ui\index.html'))) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing: $required" }
    }
    if ($WithoutTools) { throw 'The saved gateway startup requires its configured tools.' }
    $config = Get-Content -LiteralPath $mcpFile -Raw | ConvertFrom-Json
    foreach ($required in @($config.mcpServers.media.command, (Join-Path $runtimeDir 'media_tools.py'))) {
        if (-not $required -or -not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing media service file: $required" }
    }
    foreach ($port in @(8080, 8081)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::') }) { throw "Port $port is already in use; nothing was stopped." }
    }
    $reuseFiles = [bool](Get-NetTCPConnection -LocalPort 8082 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::') })
    if ($reuseFiles -and (Invoke-RestMethod 'http://127.0.0.1:8082/health' -TimeoutSec 3).service -ne 'heretic-media-files') { throw 'Port 8082 belongs to another service.' }
    if (Test-Path -LiteralPath $pidFile) {
        $previous = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        foreach ($record in $previous.Processes) {
            if (Get-Process -Id $record.Pid -ErrorAction SilentlyContinue) { throw 'Saved records reference running processes; inspect them before starting.' }
            foreach ($child in $record.Children) {
                if (Get-Process -Id $child.Pid -ErrorAction SilentlyContinue) { throw 'Saved records reference running descendants; inspect them before starting.' }
            }
        }
    }
    $records = New-Object System.Collections.Generic.List[object]
    function Save-OwnedRecords {
        $temporary = $pidFile + '.tmp'
        [pscustomobject]@{ Version = 1; Processes = @($records.ToArray()) } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $pidFile -Force
    }
    function Update-OwnedChildren($Name) {
        $record = $records | Where-Object Name -eq $Name
        $launcher = Get-Process -Id $record.Pid -ErrorAction Stop
        if ($launcher.Path -ne $record.Executable -or $launcher.StartTime.ToUniversalTime() -ne ([DateTimeOffset]$record.StartedUtc).UtcDateTime) { throw 'Launcher identity changed during startup.' }
        $children = @()
        $parents = @([int]$record.Pid)
        $depth = 0
        while ($parents.Count) {
            if (++$depth -gt 32 -or $children.Count -gt 1024) { throw 'Owned process tree exceeded its bounded tracking limit.' }
            $next = @()
            foreach ($parentId in $parents) {
                foreach ($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$parentId")) {
                    $process = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
                    if (-not $process -or $process.StartTime.ToUniversalTime() -lt $launcher.StartTime.ToUniversalTime()) { continue }
                    $children += [pscustomobject]@{ Pid = $process.Id; ParentPid = $parentId; Executable = $process.Path; StartedUtc = $process.StartTime.ToUniversalTime().ToString('o') }
                    $next += [int]$process.Id
                }
            }
            $parents = $next
        }
        $record.Children = $children
        Save-OwnedRecords
        return $record
    }
    function Start-OwnedProcess($Name, $Executable, $Arguments, $Directory) {
        $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
        $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir "$stamp.$Name.stdout.log") -RedirectStandardError (Join-Path $runtimeDir "$stamp.$Name.stderr.log")
        $process.Refresh()
        $started = $process.StartTime.ToUniversalTime().ToString('o')
        $requestedPath = [IO.Path]::GetFullPath($Executable)
        $records.Add([pscustomobject]@{ Name = $Name; Pid = $process.Id; Executable = $requestedPath; StartedUtc = $started; EffectivePid = $process.Id; Children = @() })
        Save-OwnedRecords
        $metadataReady = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            $observed = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if (-not $observed) { throw 'Owned launcher exited before its identity could be verified; records were preserved.' }
            if ($observed.Path) {
                if ($observed.Path -ne $requestedPath -or $observed.StartTime.ToUniversalTime() -ne ([DateTimeOffset]$started).UtcDateTime) { throw 'Owned launcher identity did not match its requested executable; records were preserved.' }
                $metadataReady = $true
                break
            }
            Start-Sleep -Milliseconds 100
        }
        if (-not $metadataReady) { throw 'Owned launcher identity metadata was unavailable; requested identity records were preserved.' }
        if ([IO.Path]::GetFileName($Executable) -eq 'python.exe') {
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                Start-Sleep -Milliseconds 100
                $process.Refresh()
                if ($process.HasExited) { break }
                $record = Update-OwnedChildren $Name
                if (@($record.Children | Where-Object { [IO.Path]::GetFileName($_.Executable) -eq 'python.exe' }).Count) { break }
            }
        }
        return $process
    }
    $oldUi = $env:HERETIC_UI
    try {
        $env:HERETIC_UI = Join-Path $runtimeDir 'ui'
        $gateway = Start-OwnedProcess 'gateway' $gatewayExe @('-m', 'heretic_gateway') $gatewayDir
    } finally { $env:HERETIC_UI = $oldUi }
    $gatewayReady = $false
    $gatewayDeadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $probeTimeout = [Math]::Max(1, [Math]::Min(6, [Math]::Ceiling(($gatewayDeadline - [DateTime]::UtcNow).TotalSeconds)))
        try { $gatewayReady = (Invoke-RestMethod 'http://127.0.0.1:8080/api/heretic/health' -TimeoutSec $probeTimeout).service -eq 'heretic-gateway' } catch { }
        if ($gatewayReady) { break }
        $gateway.Refresh()
        if ($gateway.HasExited) { throw 'Gateway exited during startup; inspect the gateway stderr log.' }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $gatewayDeadline)
    if (-not $gatewayReady) { throw 'Gateway startup readiness check failed; owned process records were preserved.' }
    $gatewayRecord = Update-OwnedChildren 'gateway'
    $gatewayListener = @(Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::') })
    $ownedIds = @($gatewayRecord.Pid) + @($gatewayRecord.Children | ForEach-Object Pid)
    if (-not $gatewayListener -or @($gatewayListener | Where-Object { $_.OwningProcess -notin $ownedIds }).Count) { throw 'Gateway listener is not a validated owned process; records were preserved.' }
    $gatewayRecord.EffectivePid = $gatewayListener[0].OwningProcess
    Save-OwnedRecords
    $serverArgs = @('-m', $modelFile, '--host', '127.0.0.1', '--port', '8081', '-ngl', '99', '-c', [string]$ContextSize, '-np', '1', '-fa', 'on', '--fit', 'off', '--reasoning-preserve', '--temp', '0.7', '--top-p', '0.9', '--cors-origins', 'http://127.0.0.1:8080,http://localhost:8080,http://desktop-7ov7vat.tail4c4266.ts.net:8080,http://desktop-7ov7vat:8080')
    if ($ContextSize -ge 65536) { $serverArgs += @('-ctk', 'q8_0', '-ctv', 'q8_0') }
    $serverArgs += @('--mcp-servers-config', $mcpFile)
    $model = Start-OwnedProcess 'model' $serverExe @($serverArgs | ForEach-Object { '"' + $_ + '"' }) (Join-Path $runtimeDir 'bin')
    if (-not $reuseFiles) { $files = Start-OwnedProcess 'files' $config.mcpServers.media.command @('"' + (Join-Path $runtimeDir 'media_tools.py') + '"', '--serve-files') $runtimeDir }
    foreach ($name in @($records | ForEach-Object Name)) { Update-OwnedChildren $name | Out-Null }
    [pscustomobject]@{ GatewayPid = $gateway.Id; ModelPid = $model.Id; ContextSize = $ContextSize; ProcessFile = $pidFile }
} finally {
    if ($hasLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
