$ErrorActionPreference = 'Stop'
$commit = '2459f68b5c0eb26261fd5a81682004b93cd645ba'
$sha256 = '2A69DD351F6C3AEF8769DD4FEC760FE2739002D63E61C217AF34E7AA435543A2'
$destination = Join-Path (Split-Path $PSScriptRoot -Parent) 'ui'
if (Test-Path -LiteralPath $destination) {
    throw 'ui already exists. Preserve its Heretic patches; this script only vendors into a missing directory.'
}
$archive = Join-Path ([System.IO.Path]::GetTempPath()) ('heretic-ui-' + [guid]::NewGuid().ToString() + '.tar.gz')
try {
    Invoke-WebRequest -Uri "https://github.com/ggml-org/llama.cpp/archive/$commit.tar.gz" -OutFile $archive
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $sha256) {
        throw 'Pinned upstream archive SHA256 mismatch.'
    }
    New-Item -ItemType Directory -Path $destination | Out-Null
    tar -xzf $archive --strip-components=3 -C $destination "llama.cpp-$commit/tools/ui"
    if ($LASTEXITCODE -ne 0) { throw 'UI archive extraction failed.' }
    tar -xzf $archive --strip-components=1 -C $destination "llama.cpp-$commit/LICENSE"
    if ($LASTEXITCODE -ne 0) { throw 'License archive extraction failed.' }
    Set-Content -LiteralPath (Join-Path $destination 'UPSTREAM.txt') -Value "ggml-org/llama.cpp`ncommit $commit`narchive sha256 $sha256`nvendored tools/ui and LICENSE only; local Heretic integration patches retained in Git" -Encoding utf8
} finally {
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive }
}
