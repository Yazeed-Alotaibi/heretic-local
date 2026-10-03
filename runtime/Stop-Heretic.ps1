[CmdletBinding()]
param([switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
$mutex = New-Object System.Threading.Mutex($false, 'Local\HereticSavedStartup')
$hasLock = $false
try {
    try { $hasLock = $mutex.WaitOne(120000) } catch [Threading.AbandonedMutexException] { $hasLock = $true }
    if (-not $hasLock) { throw 'Another Heretic operation did not finish within two minutes; nothing was stopped.' }
    $pidFile = Join-Path $PSScriptRoot 'heretic-processes.json'
    if (-not (Test-Path -LiteralPath $pidFile)) { throw 'No owned process records exist; nothing was stopped.' }
    $state = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    if ($state.Version -ne 1 -or -not $state.Processes) { throw 'Invalid owned process records; nothing was stopped.' }
    $validated = @()
    function Validate-OwnedIdentity($record, $ParentId) {
        $process = Get-Process -Id $record.Pid -ErrorAction SilentlyContinue
        if (-not $process) { return $null }
        try {
            $path = $process.Path
            $started = $process.StartTime.ToUniversalTime()
        } catch {
            if (-not (Get-Process -Id $record.Pid -ErrorAction SilentlyContinue)) { return $null }
            throw
        }
        if ($path -ne $record.Executable -or $started -ne ([DateTimeOffset]$record.StartedUtc).UtcDateTime) {
            $process.Refresh()
            if ($process.HasExited -or -not (Get-Process -Id $record.Pid -ErrorAction SilentlyContinue)) { return $null }
            throw "Process identity mismatch for PID $($record.Pid); nothing was stopped."
        }
        if ($ParentId) {
            $details = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.Pid)"
            if (-not $details -or $details.ParentProcessId -ne $ParentId) {
                $process.Refresh()
                if ($process.HasExited -or -not (Get-Process -Id $record.Pid -ErrorAction SilentlyContinue)) { return $null }
                throw "Process parent mismatch for PID $($record.Pid); nothing was stopped."
            }
        }
        return $process
    }
    foreach ($record in $state.Processes) {
        $process = Validate-OwnedIdentity $record $null
        $children = @($record.Children)
        $knownParents = @([int]$record.Pid)
        $validatedChildren = @()
        foreach ($child in $children) {
            if (-not $child) { continue }
            if ($child.ParentPid -notin $knownParents) { throw 'Owned child is not descended from its recorded launcher; nothing was stopped.' }
            $childProcess = Validate-OwnedIdentity $child $child.ParentPid
            $knownParents += [int]$child.Pid
            if ($childProcess) { $validatedChildren += [pscustomobject]@{ Process = $childProcess; Record = $child; ParentId = $child.ParentPid } }
        }
        [array]::Reverse($validatedChildren)
        $validated += $validatedChildren
        if ($process) { $validated += [pscustomobject]@{ Process = $process; Record = $record; ParentId = $null } }
    }
    if ($ValidateOnly) { return $validated | ForEach-Object { $_.Process | Select-Object Id, Path, StartTime } }
    # Discover late MCP/tool workers only from identities already attested above.
    # Parent PID alone is insufficient: parent creation time is rechecked on
    # both sides of every child query, and each child's creation follows it.
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    foreach ($record in $state.Processes) {
        $identities = @{}
        $identities[[int]$record.Pid] = $record
        foreach ($child in $record.Children) { if ($child) { $identities[[int]$child.Pid] = $child } }
        $queue = New-Object System.Collections.Generic.Queue[object]
        foreach ($entry in $validated) {
            if ($identities.ContainsKey([int]$entry.Record.Pid)) { $queue.Enqueue([pscustomobject]@{ Identity = $entry.Record; Depth = 0 }) }
        }
        $visited = @{}
        while ($queue.Count) {
            if ([DateTime]::UtcNow -gt $deadline -or $identities.Count -gt 1024) { throw 'Owned descendant discovery exceeded its bounded limit; nothing was stopped.' }
            $anchor = $queue.Dequeue()
            $parent = $anchor.Identity
            if ($visited.ContainsKey([int]$parent.Pid)) { continue }
            $visited[[int]$parent.Pid] = $true
            if ($anchor.Depth -ge 32) { throw 'Owned descendant discovery exceeded its depth limit; nothing was stopped.' }
            $parentParent = if ($parent.PSObject.Properties['ParentPid']) { $parent.ParentPid } else { $null }
            if (-not (Validate-OwnedIdentity $parent $parentParent)) { continue }
            $candidates = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($parent.Pid)")
            if (-not (Validate-OwnedIdentity $parent $parentParent)) { throw 'Owned parent exited during discovery; records were preserved.' }
            foreach ($candidate in $candidates) {
                if ($identities.ContainsKey([int]$candidate.ProcessId)) {
                    $known = $identities[[int]$candidate.ProcessId]
                    if ($known.ParentPid -ne $parent.Pid) { throw 'Ambiguous owned descendant ancestry; nothing was stopped.' }
                    continue
                }
                $childProcess = Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue
                if (-not $childProcess) { continue }
                $child = [pscustomobject]@{ Pid = $childProcess.Id; ParentPid = [int]$parent.Pid; Executable = $childProcess.Path; StartedUtc = $childProcess.StartTime.ToUniversalTime().ToString('o') }
                if (-not $child.Executable -or ([DateTimeOffset]$child.StartedUtc).UtcDateTime -lt ([DateTimeOffset]$parent.StartedUtc).UtcDateTime) { throw 'Ambiguous descendant identity or creation order; nothing was stopped.' }
                if (-not (Validate-OwnedIdentity $child $child.ParentPid)) { continue }
                if (-not (Validate-OwnedIdentity $parent $parentParent)) { throw 'Owned parent exited during discovery; records were preserved.' }
                $record | Add-Member -NotePropertyName Children -NotePropertyValue (@($record.Children) + @($child)) -Force
                $identities[[int]$child.Pid] = $child
                $queue.Enqueue([pscustomobject]@{ Identity = $child; Depth = $anchor.Depth + 1 })
            }
        }
    }
    $temporary = $pidFile + '.tmp'
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $pidFile -Force
    # Revalidate the complete enlarged tree before the first destructive action.
    $validated = @()
    foreach ($record in $state.Processes) {
        $children = @($record.Children)
        [array]::Reverse($children)
        foreach ($child in $children) {
            if (-not $child) { continue }
            $process = Validate-OwnedIdentity $child $child.ParentPid
            if ($process) { $validated += [pscustomobject]@{ Record = $child; ParentId = $child.ParentPid } }
        }
        $process = Validate-OwnedIdentity $record $null
        if ($process) { $validated += [pscustomobject]@{ Record = $record; ParentId = $null } }
    }
    foreach ($entry in $validated) {
        $current = Validate-OwnedIdentity $entry.Record $entry.ParentId
        if ($current) {
            $current.Kill()
            if (-not $current.WaitForExit(10000)) { throw "Owned process $($current.Id) did not exit; ownership records were preserved." }
        }
    }
    Remove-Item -LiteralPath $pidFile
} finally {
    if ($hasLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
