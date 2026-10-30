[CmdletBinding()]
param(
    [string]$RuntimePath = 'C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\ternary-bonsai-runtime'
)
# Adds the Context7 (library docs) and Hugging Face (Hub search) online MCP servers to the
# installed MCP configuration. Both reuse the existing pinned mcp-remote proxy used by Exa and
# need no account or key. Other servers and personal data are left unchanged.
$ErrorActionPreference = 'Stop'
$RuntimePath = [IO.Path]::GetFullPath($RuntimePath)
$configPath = Join-Path $RuntimePath 'heretic.mcp.json'
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { throw "Missing MCP configuration: $configPath" }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$exa = $config.mcpServers.exa
if (-not $exa -or -not $exa.command -or -not $exa.args -or $exa.args[0] -notlike '*mcp-remote*proxy.js') {
    throw 'The existing Exa server entry is required; its mcp-remote proxy is reused for the new servers.'
}
foreach ($file in @($exa.command, $exa.args[0])) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing mcp-remote prerequisite: $file" }
}
$mutex = New-Object System.Threading.Mutex($false, 'Local\HereticSavedStartup')
$hasLock = $false
try {
    try { $hasLock = $mutex.WaitOne(1000) } catch [Threading.AbandonedMutexException] { $hasLock = $true }
    if (-not $hasLock) { throw 'Heretic startup is active; retry after it finishes.' }
    foreach ($port in @(8080, 8081)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw 'Stop Heretic with its installed Stop-Heretic.ps1, then rerun this installer. No processes were stopped.'
        }
    }
    $backup = Join-Path $RuntimePath ('saved-setup\remote-tools-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff') + '-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-Item -LiteralPath $configPath -Destination (Join-Path $backup 'heretic.mcp.json')
    $servers = [ordered]@{ context7 = 'https://mcp.context7.com/mcp'; huggingface = 'https://huggingface.co/mcp' }
    foreach ($name in $servers.Keys) {
        $entry = [pscustomobject]@{ command = $exa.command; timeout_ms = 45000
            args = @($exa.args[0], $servers[$name], '--transport', 'http-only', '--silent') }
        $config.mcpServers | Add-Member -NotePropertyName $name -NotePropertyValue $entry -Force
    }
    $config | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $configPath -Encoding UTF8
    Write-Output 'Added Context7 and Hugging Face online tools.'
    Write-Output "Heretic remains stopped. Run '$RuntimePath\Open-Heretic.ps1' to start it."
    Write-Output "Rollback: copy $backup\heretic.mcp.json back over $configPath while Heretic is stopped."
} finally {
    if ($hasLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
