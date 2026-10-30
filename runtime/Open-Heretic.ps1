[CmdletBinding()]
param([ValidateSet(65536, 98304, 131072)][int]$ContextSize, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$runtimeDir = $PSScriptRoot
$logFile = Join-Path $runtimeDir 'startup-status.log'
# An explicit -ContextSize becomes the saved default for later shortcut and sign-in launches.
$contextFile = Join-Path $runtimeDir 'context-size.txt'
$allowedContexts = @(65536, 98304, 131072)
$deadline = [DateTime]::UtcNow.AddSeconds(120)
$mutex = New-Object System.Threading.Mutex($false, 'Local\HereticSavedStartup')
$hasLock = $false
function Test-OwnedGatewayListener($Listener, $Record) {
    $effectiveId = if ($Record.EffectivePid) { $Record.EffectivePid } else { $Record.Pid }
    $ownedIds = @($Record.Pid) + @($Record.Children | ForEach-Object Pid)
    if (-not $Record -or $effectiveId -notin $ownedIds -or -not $Listener -or @($Listener | Where-Object { $_.OwningProcess -ne $effectiveId }).Count) { throw 'Gateway is not owned by this saved installation; nothing was stopped.' }
}
try {
    do {
        try { $hasLock = $mutex.WaitOne(1000) } catch [Threading.AbandonedMutexException] { $hasLock = $true }
    } while (-not $hasLock -and [DateTime]::UtcNow -lt $deadline)
    if (-not $hasLock) { throw 'Another Heretic startup did not finish within two minutes.' }
    $listener = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::') }
    if ($listener) {
        $health = Invoke-RestMethod 'http://127.0.0.1:8080/api/heretic/health' -TimeoutSec 6
        if ($health.service -ne 'heretic-gateway') { throw 'Port 8080 belongs to another service; nothing was stopped.' }
        $state = Get-Content -LiteralPath (Join-Path $runtimeDir 'heretic-processes.json') -Raw | ConvertFrom-Json
        $gatewayRecord = $state.Processes | Where-Object Name -eq 'gateway'
        Test-OwnedGatewayListener $listener $gatewayRecord
        & (Join-Path $runtimeDir 'Stop-Heretic.ps1') -ValidateOnly | Out-Null
    } else {
        $startContext = if ($ContextSize) { $ContextSize } else { 65536 }
        if (-not $ContextSize -and (Test-Path -LiteralPath $contextFile)) {
            $saved = 0
            if ([int]::TryParse("$(Get-Content -LiteralPath $contextFile -Raw)".Trim(), [ref]$saved) -and $saved -in $allowedContexts) { $startContext = $saved }
        }
        & (Join-Path $runtimeDir 'Start-Heretic.ps1') -ContextSize $startContext | Out-Null
    }
    do {
        $ready = $false
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8080/api/heretic/health' -TimeoutSec 6
            $ready = $health.service -eq 'heretic-gateway' -and $health.app -eq 'ready' -and $health.model -eq 'ready' -and $health.memory -eq 'ready' -and $health.files -eq 'ready'
        } catch { }
        if ($ready) { break }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $ready) { throw 'Heretic did not become ready within two minutes; inspect the logs. Stop-Heretic.ps1 then Open-Heretic.ps1 can restart owned components after an interrupted startup.' }
    $savedModel = 'C:\Users\PC\.lmstudio\models\OS-Software\Ternary-Bonsai-2-27B-Uncensored-Heretic-GGUF\Ternary-Bonsai-2-27B-Uncensored-Heretic-PQ2_0.gguf'
    if ((Invoke-RestMethod 'http://127.0.0.1:8080/props' -TimeoutSec 5).model_path -ne $savedModel) { throw 'A different model is running; it was left intact.' }
    $slots = Invoke-RestMethod 'http://127.0.0.1:8080/slots' -TimeoutSec 5
    $runningContext = @($slots.n_ctx)[0]
    if ($ContextSize -and $runningContext -ne $ContextSize) { throw "The running model has a $runningContext-token context, not $ContextSize; it was left running. Run Stop-Heretic.ps1, then Open-Heretic.ps1 -ContextSize $ContextSize." }
    if ($runningContext -notin $allowedContexts) { throw "The running model has an unsupported $runningContext-token context; it was left running." }
    $tools = Invoke-RestMethod 'http://127.0.0.1:8080/tools' -TimeoutSec 15
    $expected = @('exa_web_search_exa', 'exa_web_fetch_exa', 'reach_backends_read_webpage', 'reach_backends_search_github_repositories', 'reach_backends_get_agent_reach_status', 'reach_backends_search_youtube', 'reach_backends_read_youtube_video', 'media_download_video', 'memory_search', 'memory_read', 'memory_propose', 'knowledge_search', 'knowledge_read')
    $mcpPath = Join-Path $runtimeDir 'heretic.mcp.json'
    $remoteWarnings = @()
    if (Test-Path -LiteralPath $mcpPath -PathType Leaf) {
        $mcpConfig = Get-Content -LiteralPath $mcpPath -Raw | ConvertFrom-Json
        if ($mcpConfig.mcpServers.filesystem) {
            $expected += @('filesystem_read_text_file', 'filesystem_list_directory', 'filesystem_search_files', 'filesystem_get_file_info', 'filesystem_list_allowed_directories', 'filesystem_write_file', 'filesystem_edit_file', 'filesystem_create_directory')
        }
        # Optional online servers: their tool names come from the remote service, so only
        # report a server that returned no tools instead of failing the local chat.
        foreach ($server in @('context7', 'huggingface')) {
            if ($mcpConfig.mcpServers.$server -and -not @($tools.tool | Where-Object { $_ -like "${server}_*" }).Count) { $remoteWarnings += $server }
        }
    }
    foreach ($toolName in $expected) {
        if ($toolName -notin $tools.tool) { throw "Saved tool is missing: $toolName. The running chat was left intact." }
    }
    if ($ContextSize) { [string]$ContextSize | Set-Content -LiteralPath $contextFile }
    $warning = if ($remoteWarnings) { " WARNING: no tools from $($remoteWarnings -join ', ') (online service unavailable?)." } else { '' }
    "$(Get-Date -Format o) READY: gateway, $($runningContext / 1024)k context, $(@($tools).Count) tools, memory, file service.$warning" | Set-Content -LiteralPath $logFile
    if (-not $NoBrowser) { Start-Process 'http://desktop-7ov7vat.tail4c4266.ts.net:8080/' }
} catch {
    "$(Get-Date -Format o) ERROR: $($_.Exception.Message)" | Set-Content -LiteralPath $logFile
    throw
} finally {
    if ($hasLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}

