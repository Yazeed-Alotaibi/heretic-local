param($LaunchFile)
$lock = New-Object System.Threading.Mutex($false, 'Local\HereticSavedStartup')
$held = $lock.WaitOne(1000)
if (-not $held) { throw 'Cannot acquire test lock' }
try {
    $child = Start-Process 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"'+$LaunchFile+'"'), '-NoBrowser') -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $child.Refresh()
    if ($child.HasExited) { throw 'Concurrent startup exited instead of waiting' }
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
if (-not $child.WaitForExit(20000)) { throw 'Concurrent startup did not complete' }
if ($child.ExitCode -ne 0) { throw 'Concurrent startup failed' }
Write-Output 'Concurrent startup waits and succeeds: PASS'
