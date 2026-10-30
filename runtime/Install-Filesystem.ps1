[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$RuntimePath = 'C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\ternary-bonsai-runtime',
    [string]$AllowedDirectory = (Join-Path $env:USERPROFILE '.heretic\files'),
    [string]$NodePath = 'C:\Program Files\nodejs\node.exe'
)
$ErrorActionPreference = 'Stop'
if (-not $RepositoryRoot) { $RepositoryRoot = Split-Path $PSScriptRoot -Parent }
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$RuntimePath = [IO.Path]::GetFullPath($RuntimePath)
$AllowedDirectory = [IO.Path]::GetFullPath($AllowedDirectory)
$NodePath = [IO.Path]::GetFullPath($NodePath)
$npm = Join-Path (Split-Path $NodePath -Parent) 'npm.cmd'
$configPath = Join-Path $RuntimePath 'heretic.mcp.json'
foreach ($file in @($NodePath, $npm, $configPath, (Join-Path $RuntimePath 'gateway\.venv\Scripts\python.exe'))) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing installation prerequisite: $file" }
}
$nodeVersion = & $NodePath --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(\d+)\.' -or [int]$Matches[1] -lt 24) {
    throw 'Filesystem MCP 2.1.0 requires Node.js 24 or newer. Update Node.js before running this installer.'
}
$packageSource = Join-Path $RepositoryRoot 'filesystem-tools'
foreach ($file in @('package.json', 'package-lock.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $packageSource $file) -PathType Leaf)) { throw "Missing install source: filesystem-tools\$file" }
}
$package = Get-Content -LiteralPath (Join-Path $packageSource 'package.json') -Raw | ConvertFrom-Json
if ($package.dependencies.'@modelcontextprotocol/server-filesystem' -ne '2.1.0') { throw 'Expected the pinned Filesystem MCP 2.1.0 dependency.' }
$gatewaySource = Join-Path $RepositoryRoot 'gateway\heretic_gateway'
$gatewayFiles = @(Get-ChildItem -LiteralPath $gatewaySource -Filter '*.py' -File)
foreach ($required in @('app.py', 'context_builder.py', 'memory_selection.py')) {
    if ($required -notin $gatewayFiles.Name) { throw "Missing gateway install source: $required" }
}
if (-not (Test-Path -LiteralPath (Join-Path $RepositoryRoot 'runtime\Open-Heretic.ps1') -PathType Leaf)) { throw 'Missing Open-Heretic.ps1 install source.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if (-not $config.mcpServers) { throw 'Existing MCP configuration has no mcpServers object.' }
$mutex = New-Object System.Threading.Mutex($false, 'Local\HereticSavedStartup')
$hasLock = $false
$changesStarted = $false
$movedOldTools = $false
$installedNewTools = $false
$journal = @()
$backup = $null
$toolsPath = Join-Path $RuntimePath 'filesystem-tools'
try {
    try { $hasLock = $mutex.WaitOne(1000) } catch [Threading.AbandonedMutexException] { $hasLock = $true }
    if (-not $hasLock) { throw 'Heretic startup is active; retry after it finishes.' }
    foreach ($port in @(8080, 8081)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw 'Stop Heretic with its installed Stop-Heretic.ps1, then rerun this installer. No processes were stopped.'
        }
    }
    $backup = Join-Path $RuntimePath ('saved-setup\filesystem-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff') + '-' + [Guid]::NewGuid().ToString('N'))
    $stage = Join-Path $backup 'staged-filesystem-tools'
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    foreach ($file in @('package.json', 'package-lock.json')) { Copy-Item -LiteralPath (Join-Path $packageSource $file) -Destination $stage }
    $oldPath = $env:PATH
    Push-Location $stage
    try {
        $env:PATH = (Split-Path $NodePath -Parent) + ';' + $oldPath
        & $npm ci --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE; the installed setup is unchanged." }
    } finally { $env:PATH = $oldPath; Pop-Location }
    $entry = 'node_modules\@modelcontextprotocol\server-filesystem\dist\index.js'
    if (-not (Test-Path -LiteralPath (Join-Path $stage $entry) -PathType Leaf)) { throw 'Installed filesystem server entry point is missing.' }
    $installed = Get-Content -LiteralPath (Join-Path $stage 'node_modules\@modelcontextprotocol\server-filesystem\package.json') -Raw | ConvertFrom-Json
    if ($installed.version -ne '2.1.0') { throw 'Installed filesystem server does not match the pinned version.' }
    $relativeFiles = @('heretic.mcp.json', 'Open-Heretic.ps1') + @($gatewayFiles | ForEach-Object { 'gateway\heretic_gateway\' + $_.Name })
    foreach ($relative in $relativeFiles) {
        $target = Join-Path $RuntimePath $relative
        $saved = Join-Path (Join-Path $backup 'files') $relative
        $existed = Test-Path -LiteralPath $target -PathType Leaf
        if ($existed) {
            New-Item -ItemType Directory -Path (Split-Path $saved -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $target -Destination $saved
        }
        $journal += [pscustomobject]@{ RelativePath = $relative; Existed = $existed }
    }
    [pscustomobject]@{ RuntimePath = $RuntimePath; AllowedDirectory = $AllowedDirectory; Files = $journal } |
        ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $backup 'manifest.json') -Encoding UTF8
    $changesStarted = $true
    if (Test-Path -LiteralPath $toolsPath) {
        Move-Item -LiteralPath $toolsPath -Destination (Join-Path $backup 'previous-filesystem-tools')
        $movedOldTools = $true
    }
    Move-Item -LiteralPath $stage -Destination $toolsPath
    $installedNewTools = $true
    New-Item -ItemType Directory -Path $AllowedDirectory -Force | Out-Null
    foreach ($file in $gatewayFiles) {
        Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $RuntimePath ('gateway\heretic_gateway\' + $file.Name)) -Force
    }
    Copy-Item -LiteralPath (Join-Path $RepositoryRoot 'runtime\Open-Heretic.ps1') -Destination (Join-Path $RuntimePath 'Open-Heretic.ps1') -Force
    $filesystem = [pscustomobject]@{ command = $NodePath; cwd = $RuntimePath; timeout_ms = 30000; args = @((Join-Path $toolsPath $entry), $AllowedDirectory) }
    $config.mcpServers | Add-Member -NotePropertyName filesystem -NotePropertyValue $filesystem -Force
    $config | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $configPath -Encoding UTF8
    Write-Output "Filesystem MCP installed with read/search access to: $AllowedDirectory"
    Write-Output "Heretic remains stopped. Run '$RuntimePath\Open-Heretic.ps1' to start and check the five filesystem tools."
    Write-Output "Rollback backup: $backup (see docs/filesystem-mcp.md in the repository)."
} catch {
    if ($changesStarted) {
        foreach ($item in $journal) {
            $target = Join-Path $RuntimePath $item.RelativePath
            if ($item.Existed) { Copy-Item -LiteralPath (Join-Path (Join-Path $backup 'files') $item.RelativePath) -Destination $target -Force }
            elseif (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target }
        }
        if ($installedNewTools) { Move-Item -LiteralPath $toolsPath -Destination (Join-Path $backup 'failed-filesystem-tools') }
        if ($movedOldTools) { Move-Item -LiteralPath (Join-Path $backup 'previous-filesystem-tools') -Destination $toolsPath }
    }
    throw
} finally {
    if ($hasLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
