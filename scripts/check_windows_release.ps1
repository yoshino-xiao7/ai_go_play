param([Parameter(Mandatory)][string]$PackageDir)

$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath (Join-Path $PackageDir 'release-manifest.json') -Raw | ConvertFrom-Json
$archive = Join-Path $PackageDir $manifest.asset
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $manifest.sha256) {
    throw 'The Windows candidate ZIP failed SHA-256 verification.'
}

$testRoot = Join-Path $env:RUNNER_TEMP ('ai-go-play smoke ' + [guid]::NewGuid().ToString('N'))
$workspace = Join-Path $testRoot "ai-go-play-$($manifest.version)"
$dataDir = Join-Path $testRoot 'data'
$configFile = Join-Path $testRoot 'config.json'
Expand-Archive -LiteralPath $archive -DestinationPath $testRoot

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
$listener.Stop()
$url = "http://127.0.0.1:$port"
$env:MANJU_DOWNLOAD_SOURCE = 'overseas'
$windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

try {
    & $windowsPowerShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $workspace 'start.ps1') `
        -Port $port -DataDir $dataDir -ConfigFile $configFile -NoBrowser
    if ($LASTEXITCODE -ne 0) { throw "The packaged launcher exited with code $LASTEXITCODE." }

    $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 5
    if (!$health.ok -or $health.version -ne $manifest.version -or $health.root -ne $dataDir) {
        throw 'The extracted package did not start with the expected version and isolated library.'
    }
    $setup = Invoke-RestMethod -Uri "$url/api/setup" -TimeoutSec 5
    if ($setup.completed -ne $false) { throw 'The first-run setup API did not return a fresh state.' }
    $page = Invoke-WebRequest -Uri "$url/" -TimeoutSec 5
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch '<html\b') {
        throw 'The extracted package did not serve the built web application.'
    }

    $processPath = Join-Path $env:LOCALAPPDATA "Manju\run\server-$port.json"
    $server = Get-Content -LiteralPath $processPath -Raw | ConvertFrom-Json
    $serverProcess = Get-Process -Id $server.pid
    $shutdown = Invoke-RestMethod -Uri "$url/api/system/shutdown" -Method Post -TimeoutSec 10 `
        -ContentType 'application/json' -Body '{"confirm":true,"stop_comfy":false}'
    if (!$shutdown.accepted) { throw 'The packaged server rejected graceful shutdown.' }
    Wait-Process -InputObject $serverProcess -Timeout 15
    Write-Host 'Windows ZIP passed clean startup, first-run API, web serving and graceful shutdown.'
} catch {
    $statusPath = Join-Path $workspace '.manju\bootstrap\status.json'
    if (Test-Path -LiteralPath $statusPath) { Get-Content -LiteralPath $statusPath | Write-Host }
    throw
}
