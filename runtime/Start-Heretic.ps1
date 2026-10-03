[CmdletBinding()]
param(
    [ValidateSet(8192, 65536)][int]$ContextSize = 65536,
    [switch]$WithoutTools
)
$ErrorActionPreference = 'Stop'
$runtimeDir = $PSScriptRoot
$serverExe = Join-Path $runtimeDir 'bin\llama-server.exe'
$modelFile = 'C:\Users\PC\.lmstudio\models\OS-Software\Ternary-Bonsai-2-27B-Uncensored-Heretic-GGUF\Ternary-Bonsai-2-27B-Uncensored-Heretic-PQ2_0.gguf'
$mcpFile = Join-Path $runtimeDir 'heretic.mcp.json'
foreach ($requiredFile in @($serverExe, $modelFile)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) { throw "Missing: $requiredFile" }
}
if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::') }) {
    throw 'Port 8080 is already in use. Stop the intended Heretic instance before starting another.'
}
$serverArgs = @('-m', $modelFile, '--host', '127.0.0.1', '--port', '8080',
    '-ngl', '99', '-c', [string]$ContextSize, '-np', '1', '-fa', 'on', '--fit', 'off',
    '--reasoning-preserve', '--cors-origins',
    'http://127.0.0.1:8080,http://localhost:8080,http://desktop-7ov7vat.tail4c4266.ts.net:8080,http://desktop-7ov7vat:8080')
if ($ContextSize -eq 65536) { $serverArgs += @('-ctk', 'q8_0', '-ctv', 'q8_0') }
if (-not $WithoutTools) {
    if (-not (Test-Path -LiteralPath $mcpFile -PathType Leaf)) { throw "Missing: $mcpFile" }
    $toolConfig = Get-Content -LiteralPath $mcpFile -Raw | ConvertFrom-Json
    if ($toolConfig.mcpServers.media) {
        $mediaScript = Join-Path $runtimeDir 'media_tools.py'
        $mediaPython = $toolConfig.mcpServers.media.command
        if (Get-NetTCPConnection -LocalPort 8082 -State Listen -ErrorAction SilentlyContinue) {
            $mediaHealth = Invoke-RestMethod 'http://127.0.0.1:8082/health' -TimeoutSec 3
            if ($mediaHealth.service -ne 'heretic-media-files') { throw 'Port 8082 belongs to another service.' }
        } else {
            $mediaStamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
            $mediaProcess = Start-Process -FilePath $mediaPython -ArgumentList @('"' + $mediaScript + '"', '--serve-files') `
                -WorkingDirectory $runtimeDir -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $runtimeDir "$mediaStamp.media.stdout.log") `
                -RedirectStandardError (Join-Path $runtimeDir "$mediaStamp.media.stderr.log")
            $mediaReady = $false
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                Start-Sleep -Milliseconds 250
                try { $mediaReady = (Invoke-RestMethod 'http://127.0.0.1:8082/health' -TimeoutSec 1).service -eq 'heretic-media-files' } catch { }
                if ($mediaReady -or $mediaProcess.HasExited) { break }
            }
            if (-not $mediaReady) {
                if (-not $mediaProcess.HasExited) { Stop-Process -Id $mediaProcess.Id -Force }
                throw 'Private video file service failed to start.'
            }
        }
    }
    $serverArgs += @('--mcp-servers-config', $mcpFile)
}
$quotedArgs = @($serverArgs | ForEach-Object { '"' + $_ + '"' })
$runStamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff', [Globalization.CultureInfo]::InvariantCulture)
$logPrefix = Join-Path $runtimeDir "$runStamp.heretic"
$serverProcess = Start-Process -FilePath $serverExe -ArgumentList $quotedArgs `
    -WorkingDirectory (Join-Path $runtimeDir 'bin') -WindowStyle Hidden `
    -RedirectStandardOutput "$logPrefix.stdout.log" -RedirectStandardError "$logPrefix.stderr.log" -PassThru
[pscustomobject]@{ Pid = $serverProcess.Id; ContextSize = $ContextSize; LogPrefix = $logPrefix }
