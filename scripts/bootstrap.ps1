param([string]$Workspace, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$stateDir = Join-Path $Workspace '.manju\bootstrap'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
function Set-BootstrapStatus([string]$Phase,[double]$Progress,[string]$State='running',[string]$Failure='') {
    $value = @{phase=$Phase;progress=$Progress;status=$State;error=$Failure} | ConvertTo-Json
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
        $spec = Get-Content (Join-Path $Workspace 'scripts\local_ai\sources.json') -Raw | ConvertFrom-Json
        $core = Get-Content (Join-Path $Workspace 'release\setup-sources.json') -Raw | ConvertFrom-Json
        $archive = Join-Path $stateDir 'uv.zip'
        Set-BootstrapStatus 'Downloading environment manager' 0.04
        if (!(Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.uv.sha256) {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $webClient = New-Object Net.WebClient
            try {$webClient.DownloadFile($spec.uv.url, $archive + '.partial')} finally {$webClient.Dispose()}
            if ((Get-FileHash -LiteralPath ($archive + '.partial') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.uv.sha256) {throw 'Environment manager checksum failed.'}
            Move-Item -LiteralPath ($archive + '.partial') -Destination $archive -Force
        }
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $stateDir 'uv') -Force
        $uv = Join-Path $stateDir 'uv\uv.exe'
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $stateDir 'python'
        $env:UV_CACHE_DIR = Join-Path $stateDir 'cache\uv'
        $env:UV_PYTHON_PREFERENCE = 'only-managed'
        $env:UV_NO_CONFIG='1'; $env:UV_NO_PROJECT='1'; $env:UV_LINK_MODE='copy'
        $env:TEMP=Join-Path $stateDir 'tmp'; $env:TMP=$env:TEMP
        New-Item -ItemType Directory -Force -Path $env:TEMP,$env:UV_CACHE_DIR | Out-Null
        Set-BootstrapStatus 'Installing private Python' 0.1
        & $uv python install $core.python_version --no-bin --no-registry
        if ($LASTEXITCODE -ne 0) {throw 'Python download failed. Check the network and retry.'}
        $python = & $uv python find $core.python_version
        if ($LASTEXITCODE -ne 0) {throw 'Private Python was not found.'}
        & $python -I -X utf8 -u (Join-Path $PSScriptRoot 'bootstrap_core.py') --project $Workspace --uv $uv --state-dir $stateDir
        if ($LASTEXITCODE -ne 0) {throw "Environment setup failed. See $stateDir\logs for details."}
        break
    } catch {
        Set-BootstrapStatus 'Environment preparation failed' 0 'failed' $_.Exception.Message
        if ($NoBrowser) {throw}
        $retryFile=Join-Path $stateDir 'retry.request'
        while (!(Test-Path -LiteralPath $retryFile)) {Start-Sleep -Milliseconds 500}
        Remove-Item -LiteralPath $retryFile
        Set-BootstrapStatus 'Retrying environment preparation' 0.02
    }
}
