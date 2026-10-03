[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$RuntimePath = 'C:\Users\PC\OneDrive\Documents\ChatGPT\chats with no projects\ternary-bonsai-runtime',
    [string]$RollbackBackup
)
$ErrorActionPreference = 'Stop'
if (-not $RepositoryRoot) { $RepositoryRoot = Split-Path $PSScriptRoot -Parent }
$RuntimePath = [IO.Path]::GetFullPath($RuntimePath)
if (-not (Test-Path -LiteralPath $RuntimePath -PathType Container)) { throw "Missing runtime: $RuntimePath" }
$launchers = @('Start-Heretic.ps1', 'Open-Heretic.ps1', 'Stop-Heretic.ps1', 'Test-SavedStartup.ps1', 'README-Heretic.md', 'Install-Gateway.ps1')
if ($RollbackBackup) {
    $RollbackBackup = [IO.Path]::GetFullPath($RollbackBackup)
    $manifest = Get-Content -LiteralPath (Join-Path $RollbackBackup 'manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.RuntimePath -ne $RuntimePath) { throw 'Backup belongs to a different runtime.' }
    foreach ($name in $launchers) {
        $source = Join-Path $RollbackBackup $name
        if (Test-Path -LiteralPath $source -PathType Leaf) { Copy-Item -LiteralPath $source -Destination (Join-Path $RuntimePath $name) -Force }
    }
    Write-Output "Original launchers restored from $RollbackBackup. Start the original model only after the gateway has been stopped."
    return
}
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
foreach ($file in @('gateway\pyproject.toml', 'gateway\uv.lock', 'ui\dist\index.html')) {
    if (-not (Test-Path -LiteralPath (Join-Path $RepositoryRoot $file) -PathType Leaf)) { throw "Missing install source: $file" }
}
$backup = Join-Path $RuntimePath ('saved-setup\gateway-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff') + '-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($name in $launchers) {
    $existing = Join-Path $RuntimePath $name
    if (Test-Path -LiteralPath $existing -PathType Leaf) { Copy-Item -LiteralPath $existing -Destination (Join-Path $backup $name) }
}
[pscustomobject]@{ RuntimePath = $RuntimePath; CreatedUtc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'manifest.json') -Encoding UTF8
foreach ($directory in @('gateway', 'ui')) {
    $existing = Join-Path $RuntimePath $directory
    if (Test-Path -LiteralPath $existing) { Copy-Item -LiteralPath $existing -Destination (Join-Path $backup $directory) -Recurse }
    New-Item -ItemType Directory -Path $existing -Force | Out-Null
}
$gateway = Join-Path $RuntimePath 'gateway'
foreach ($name in @('pyproject.toml', 'uv.lock')) { Copy-Item -LiteralPath (Join-Path $RepositoryRoot "gateway\$name") -Destination (Join-Path $gateway $name) -Force }
$packageSource = Join-Path $RepositoryRoot 'gateway\heretic_gateway'
foreach ($file in Get-ChildItem -LiteralPath $packageSource -Filter '*.py' -File -Recurse) {
    $relative = $file.FullName.Substring($packageSource.Length).TrimStart('\')
    $target = Join-Path $gateway (Join-Path 'heretic_gateway' $relative)
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
}
Get-ChildItem -LiteralPath (Join-Path $RepositoryRoot 'ui\dist') | Copy-Item -Destination (Join-Path $RuntimePath 'ui') -Recurse -Force
Push-Location $gateway
try {
    & uv sync --frozen --python 3.12 --link-mode copy
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed with exit code $LASTEXITCODE. Backup: $backup" }
} finally { Pop-Location }
foreach ($name in $launchers) { Copy-Item -LiteralPath (Join-Path $RepositoryRoot "runtime\$name") -Destination (Join-Path $RuntimePath $name) -Force }
Write-Output "Installed gateway and UI; services were not changed. Rollback backup: $backup"
