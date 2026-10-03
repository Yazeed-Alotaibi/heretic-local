[CmdletBinding()]
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$runtimeDir = $PSScriptRoot
$logFile = Join-Path $runtimeDir 'startup-status.log'
$deadline = [DateTime]::UtcNow.AddSeconds(120)
try {
    # Serializes desktop/login launches without restarting an existing chat.
    $mutex = [Threading.Mutex]::new($false, 'Local\HereticSavedStartup')
    $hasLock = $false
    try {
        do {
            try { $hasLock = $mutex.WaitOne(1000) } catch [Threading.AbandonedMutexException] { $hasLock = $true }
        } while (-not $hasLock -and [DateTime]::UtcNow -lt $deadline)
        if (-not $hasLock) { throw 'Another Heretic startup did not finish within two minutes.' }
        $listener = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
            Where-Object LocalAddress -in @('127.0.0.1', '0.0.0.0', '::')
        if ($listener) {
            $existing = Get-Process -Id $listener[0].OwningProcess
            if ($existing.Path -ne (Join-Path $runtimeDir 'bin\llama-server.exe')) {
                throw 'Port 8080 is occupied by another application; nothing was stopped.'
            }
        } else {
            & (Join-Path $runtimeDir 'Start-Heretic.ps1') -ContextSize 65536 | Out-Null
        }
        do {
            $ready = $false
            try { $ready = (Invoke-RestMethod 'http://127.0.0.1:8080/health' -TimeoutSec 2).status -eq 'ok' } catch { }
            if ($ready) { break }
            Start-Sleep -Seconds 1
        } while ([DateTime]::UtcNow -lt $deadline)
        if (-not $ready) { throw 'Heretic did not become ready within two minutes; inspect the latest server log.' }
        $savedModel = 'C:\Users\PC\.lmstudio\models\OS-Software\Ternary-Bonsai-2-27B-Uncensored-Heretic-GGUF\Ternary-Bonsai-2-27B-Uncensored-Heretic-PQ2_0.gguf'
        if ((Invoke-RestMethod 'http://127.0.0.1:8080/props' -TimeoutSec 5).model_path -ne $savedModel) {
            throw 'A different model is running; it was left intact.'
        }
        $slots = Invoke-RestMethod 'http://127.0.0.1:8080/slots' -TimeoutSec 5
        if ($slots.n_ctx -notcontains 65536) { throw 'The running model does not have the saved 64k context; it was left running.' }
        $tools = Invoke-RestMethod 'http://127.0.0.1:8080/tools' -TimeoutSec 15
        $expected = @('exa_web_search_exa', 'exa_web_fetch_exa', 'reach_backends_read_webpage',
            'reach_backends_search_github_repositories', 'reach_backends_get_agent_reach_status',
            'reach_backends_search_youtube', 'reach_backends_read_youtube_video', 'media_download_video')
        foreach ($toolName in $expected) {
            if ($toolName -notin $tools.tool) { throw "Saved tool is missing: $toolName. The running chat was left intact." }
        }
        $mediaListener = Get-NetTCPConnection -LocalPort 8082 -State Listen -ErrorAction SilentlyContinue
        if (-not $mediaListener) {
            $config = Get-Content (Join-Path $runtimeDir 'heretic.mcp.json') -Raw | ConvertFrom-Json
            $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
            $mediaProcess = Start-Process -FilePath $config.mcpServers.media.command `
                -ArgumentList @('"' + (Join-Path $runtimeDir 'media_tools.py') + '"', '--serve-files') `
                -WorkingDirectory $runtimeDir -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $runtimeDir "$stamp.media.stdout.log") `
                -RedirectStandardError (Join-Path $runtimeDir "$stamp.media.stderr.log")
            $mediaReady = $false
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                Start-Sleep -Milliseconds 250
                try { $mediaReady = (Invoke-RestMethod 'http://127.0.0.1:8082/health' -TimeoutSec 1).service -eq 'heretic-media-files' } catch { }
                if ($mediaReady -or $mediaProcess.HasExited) { break }
            }
            if (-not $mediaReady) {
                if (-not $mediaProcess.HasExited) { Stop-Process -Id $mediaProcess.Id -Force }
                throw 'The saved video file service failed to start.'
            }
        }
        if ((Invoke-RestMethod 'http://127.0.0.1:8082/health' -TimeoutSec 3).service -ne 'heretic-media-files') {
            throw 'Port 8082 belongs to a different service.'
        }
        "$(Get-Date -Format o) READY: 64k context, all eight tools, video file server." | Set-Content -LiteralPath $logFile
    } finally {
        if ($hasLock) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
    if (-not $NoBrowser) { Start-Process 'http://desktop-7ov7vat.tail4c4266.ts.net:8080/' }
} catch {
    "$(Get-Date -Format o) ERROR: $($_.Exception.Message)" | Set-Content -LiteralPath $logFile
    throw
}
