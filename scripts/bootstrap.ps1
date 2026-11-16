param([string]$Workspace, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
. (Join-Path $PSScriptRoot 'bootstrap-sources.ps1')
$stateDir = Join-Path $Workspace '.manju\bootstrap'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
function Set-BootstrapStatus([string]$Phase,[double]$Progress,[string]$State='running',[string]$Failure='',[string]$Detail='') {
    $value = @{phase=$Phase;progress=$Progress;status=$State;error=$Failure;detail=$Detail;source=$env:MANJU_DOWNLOAD_SOURCE} | ConvertTo-Json
    $temporary = Join-Path $stateDir ('status-' + [guid]::NewGuid().ToString('N') + '.tmp')
    [IO.File]::WriteAllText($temporary, $value, (New-Object Text.UTF8Encoding($false)))
    for ($retry=0; $retry -lt 8; $retry++) {
        try { Move-Item -LiteralPath $temporary -Destination (Join-Path $stateDir 'status.json') -Force; break }
        catch { if ($retry -eq 7) { throw }; Start-Sleep -Milliseconds 80 }
    }
}
Set-BootstrapStatus 'Preparing local environment' 0.02
if (!$NoBrowser) {
    $token = [guid]::NewGuid().ToString('N')
    $webFile = Join-Path $stateDir 'web.json'
    if (Test-Path -LiteralPath $webFile) { Remove-Item -LiteralPath $webFile }
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'bootstrap-web.ps1') + '" -StateDir "' + $stateDir + '" -PagePath "' + (Join-Path $PSScriptRoot 'bootstrap.html') + '" -Token ' + $token
    Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -WindowStyle Hidden | Out-Null
    for ($attempt=0;$attempt -lt 80 -and !(Test-Path -LiteralPath $webFile);$attempt++) {Start-Sleep -Milliseconds 100}
    if (!(Test-Path -LiteralPath $webFile)) {throw 'Bootstrap web page could not start.'}
    $web = Get-Content -LiteralPath $webFile -Raw | ConvertFrom-Json
    Start-Process "http://127.0.0.1:$($web.port)/"
}
while ($true) {
    try {
        Initialize-DownloadSource
        $spec = Get-Content (Join-Path $Workspace 'scripts\local_ai\sources.json') -Raw | ConvertFrom-Json
        $core = Get-Content (Join-Path $Workspace 'release\setup-sources.json') -Raw | ConvertFrom-Json
        Set-BootstrapStatus 'Downloading environment manager' 0.04
        $uv = Get-PinnedUv $spec.uv $stateDir { param($detail) Set-BootstrapStatus 'Downloading environment manager' 0.04 -Detail $detail }
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $stateDir 'python'
        $env:UV_CACHE_DIR = Join-Path $stateDir 'cache\uv'
        $env:UV_PYTHON_PREFERENCE = 'only-managed'
        $env:UV_NO_CONFIG='1'; $env:UV_NO_PROJECT='1'; $env:UV_LINK_MODE='copy'
        $env:TEMP=Join-Path $stateDir 'tmp'; $env:TMP=$env:TEMP
        New-Item -ItemType Directory -Force -Path $env:TEMP,$env:UV_CACHE_DIR | Out-Null
        Set-BootstrapStatus 'Installing private Python' 0.1
        $python = Install-ManagedPython $uv $core.python_version { param($detail) Set-BootstrapStatus 'Installing private Python' 0.10 -Detail $detail }
        & $python -I -X utf8 -u (Join-Path $PSScriptRoot 'bootstrap_core.py') --project $Workspace --uv $uv --state-dir $stateDir
        if ($LASTEXITCODE -ne 0) {throw "Environment setup failed. See $stateDir\logs for details."}
        break
    } catch {
        $failure = $null
        try {
            $failure = Get-Content -LiteralPath (Join-Path $stateDir 'status.json') -Encoding UTF8 -Raw | ConvertFrom-Json
        } catch {}
        if ($failure.status -ne 'failed' -or !$failure.error) {
            $failedPhase = if ($failure.phase) { 'Failed: ' + $failure.phase } else { 'Environment preparation failed' }
            Set-BootstrapStatus $failedPhase ([double]$failure.progress) 'failed' $_.Exception.Message $failure.detail
        } elseif ($NoBrowser) {
            throw $failure.error
        }
        if ($NoBrowser) {throw}
        $retryFile=Join-Path $stateDir 'retry.request'
        while (!(Test-Path -LiteralPath $retryFile)) {Start-Sleep -Milliseconds 500}
        $requestedSource = [IO.File]::ReadAllText($retryFile)
        if ($requestedSource -in @('china','overseas')) { $env:MANJU_DOWNLOAD_SOURCE = $requestedSource }
        if ($requestedSource -eq 'auto') { $env:MANJU_DOWNLOAD_SOURCE = $null }
        Remove-Item -LiteralPath $retryFile
        Set-BootstrapStatus 'Retrying environment preparation' 0.02
    }
}
