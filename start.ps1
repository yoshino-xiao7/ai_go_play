[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$DataDir,
    [string]$ConfigFile,
    [switch]$NoBrowser,
    [string]$ErrorLogPath
)

$ErrorActionPreference = 'Stop'
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$workspace = $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$serverPython = Join-Path $workspace '.venv\Scripts\pythonw.exe'
$url = "http://127.0.0.1:$Port"
$runtime = Join-Path $env:LOCALAPPDATA 'Manju\run'
$bootstrapOpened = $false

function Get-ManjuHealth {
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
        if ($health.ok -eq $true -and $health.version -and $health.root) {
            return $health
        }
    } catch {
        return $null
    }
    return $null
}

function Open-ExistingPreparation {
    $webFile = Join-Path $workspace '.manju\bootstrap\web.json'
    try {
        if (-not (Test-Path -LiteralPath $webFile)) { return $false }
        $web = Get-Content -LiteralPath $webFile -Raw | ConvertFrom-Json
        $preparationUrl = "http://127.0.0.1:$([int]$web.port)/"
        $status = Invoke-RestMethod -Uri ($preparationUrl + 'status') -TimeoutSec 2
        if ($status.status -notin @('running', 'failed')) { return $false }
        Write-Host "Environment preparation is already running: $preparationUrl"
        if (-not $NoBrowser) { Start-Process $preparationUrl }
        return $true
    } catch { return $false }
}

while ($true) {
$mutex = New-Object System.Threading.Mutex($false, "Local\Manju.Start.$Port")
$acquired = $false
try {
    try {
        $acquired = $mutex.WaitOne(0)
        if (-not $acquired -and (Open-ExistingPreparation)) { exit 0 }
        if (-not $acquired) { $acquired = $mutex.WaitOne(30000) }
    } catch [System.Threading.AbandonedMutexException] {
        $acquired = $true
    }
    if (-not $acquired) { throw 'Another startup is still running. Please retry in a moment.' }
    $health = Get-ManjuHealth
    if ($health) {
        Write-Host "ai-go-play is running at $url"
        Write-Host "Storage: $($health.root)"
        if (-not $NoBrowser) { Start-Process $url }
        exit 0
    }
    if (-not (Test-Path -LiteralPath (Join-Path $workspace 'scripts\bootstrap.ps1'))) {
        throw 'Project files are missing. Download or clone the complete ai-go-play project, then run start.cmd from its root directory.'
    }
    & (Join-Path $workspace 'scripts\bootstrap.ps1') -Workspace $workspace -NoBrowser:($NoBrowser -or $bootstrapOpened)
    if (-not $NoBrowser) { $bootstrapOpened = $true }
    $dependencyCheck = @'
import sys
try:
    import manju.cli, fastapi, uvicorn, multipart, PIL, httpx, psutil, websocket
except ImportError:
    sys.exit(1)
'@
    & $python -I -X utf8 -c $dependencyCheck
    if ($LASTEXITCODE -ne 0) {
        throw "Dependencies are missing. Run in '$workspace':`n.\.venv\Scripts\python -m pip install -c requirements.lock -e '.[dev]'"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $workspace 'frontend\dist\index.html'))) {
        throw "Frontend build is missing. Run in '$workspace':`nnpm --prefix frontend ci`nnpm --prefix frontend run build"
    }
    $connection = New-Object System.Net.Sockets.TcpClient
    try {
        $connection.Connect('127.0.0.1', $Port)
        throw "Port $Port is occupied by another service. Stop that service or run .\start.ps1 -Port 8766."
    } catch [System.Net.Sockets.SocketException] {
        # An unused local port is expected before launch.
    } finally {
        $connection.Dispose()
    }
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $stdout = Join-Path $runtime "server-$Port.out.log"
    $stderr = Join-Path $runtime "server-$Port.err.log"
    $arguments = @($serverPython, '-I', '-X', 'utf8', '-m', 'manju', 'serve', '--port', "$Port")
    if ($DataDir) { $arguments += @('--data-dir', $DataDir) }
    if ($ConfigFile) { $arguments += @('--config-file', $ConfigFile) }
    $defaultConfiguration = -not ($DataDir -or $ConfigFile -or $env:MANJU_DATA_DIR -or $env:MANJU_CONFIG_FILE)
    $anchorPath = Join-Path $workspace '.manju\launcher.json'
    $launcher = @'
import json
import os
from pathlib import Path
import subprocess
import sys

settings = json.loads(sys.stdin.buffer.read())
try:
    media_paths = json.loads((Path(settings['cwd']) / '.manju/local-ai-paths.json').read_text(encoding='utf-8'))
    child_env = dict(os.environ)
    child_env.update(MANJU_FFMPEG=media_paths['ffmpeg'], MANJU_FFPROBE=media_paths['ffprobe'])
    config_file = None
    if settings['default_configuration']:
        anchor = Path(settings['anchor_path'])
        if anchor.exists():
            saved = json.loads(anchor.read_text(encoding='utf-8-sig'))
            value = saved.get('config_file') if isinstance(saved, dict) else None
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError('Invalid config_file in launcher anchor: ' + str(anchor))
            config_file = Path(value)
            if not config_file.parent.is_dir():
                raise OSError('Saved configuration directory is unavailable: ' + str(config_file.parent))
        else:
            from manju.app import resolve_configuration
            _, config_file = resolve_configuration(None, None)
            config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file = config_file.parent.resolve(strict=True) / config_file.name
        settings['arguments'].extend(['--config-file', str(config_file)])
    with open(settings['stdout'], 'ab', buffering=0) as output, open(settings['stderr'], 'ab', buffering=0) as errors:
        process = subprocess.Popen(
            settings['arguments'],
            cwd=settings['cwd'],
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    print(json.dumps({'pid': process.pid, 'config_file': str(config_file) if config_file else None}), flush=True)
except (OSError, ValueError, RuntimeError) as error:
    print(json.dumps({'error': str(error)}), flush=True)
    sys.exit(1)
'@
    $launchSettings = @{ arguments = $arguments; cwd = $workspace; stdout = $stdout; stderr = $stderr; default_configuration = $defaultConfiguration; anchor_path = $anchorPath }
    $previousOutputEncoding = $OutputEncoding
    try {
        $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $launchText = $launchSettings | ConvertTo-Json -Depth 4 -Compress | & $python -I -X utf8 -c $launcher
        $launchExitCode = $LASTEXITCODE
        $launchResult = $launchText | ConvertFrom-Json
        if ($launchResult.error) { throw $launchResult.error }
        if ($launchExitCode -ne 0) { throw 'Unable to launch the detached service. Check the Python error above.' }
        $serverProcessId = [int]$launchResult.pid
    } finally {
        $OutputEncoding = $previousOutputEncoding
    }
    @{ pid = $serverProcessId; port = $Port; workspace = $workspace; started_at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime "server-$Port.json") -Encoding UTF8
    $process = Get-Process -Id $serverProcessId
    $deadline = (Get-Date).AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 250
        $process.Refresh()
        if ($process.HasExited) { throw "Service exited. Read '$stderr' for the error." }
        $health = Get-ManjuHealth
    } while (-not $health -and (Get-Date) -lt $deadline)
    if (-not $health) { throw "Service is still starting. Read '$stderr', then open $url." }
    if ($defaultConfiguration -and -not (Test-Path -LiteralPath $anchorPath)) {
        $anchorDirectory = Split-Path -Parent $anchorPath
        New-Item -ItemType Directory -Force -Path $anchorDirectory | Out-Null
        $anchorTemporary = Join-Path $anchorDirectory ('.launcher-' + [guid]::NewGuid().ToString('N') + '.tmp')
        try {
            $anchorContent = @{ config_file = $launchResult.config_file } | ConvertTo-Json
            [System.IO.File]::WriteAllText($anchorTemporary, $anchorContent, (New-Object System.Text.UTF8Encoding($false)))
            [System.IO.File]::Move($anchorTemporary, $anchorPath)
        } finally {
            if (Test-Path -LiteralPath $anchorTemporary) { Remove-Item -LiteralPath $anchorTemporary }
        }
    }
    Write-Host "Manju is ready at $url"
    Write-Host "Storage: $($health.root)"
    Write-Host "Logs: $runtime"
    $bootstrapStatus = Join-Path $workspace '.manju\bootstrap\status.json'
    [IO.File]::WriteAllText($bootstrapStatus, (@{status='ready';phase='Ready';progress=1;url=$url} | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    if (-not $NoBrowser -and -not $bootstrapOpened) { Start-Process $url }
    break
} catch {
    $failureMessage = $_.Exception.Message
    Write-Host $failureMessage -ForegroundColor Red
    try {
        New-Item -ItemType Directory -Force -Path $runtime | Out-Null
        if (-not $ErrorLogPath) { $ErrorLogPath = Join-Path $runtime "launcher-$Port.log" }
        $failureMessage | Set-Content -LiteralPath $ErrorLogPath -Encoding Unicode
        Write-Host "Startup error log: $ErrorLogPath"
    } catch {
        Write-Host "Unable to save the startup error log: $($_.Exception.Message)" -ForegroundColor Red
    }
    $bootstrapStatus = Join-Path $workspace '.manju\bootstrap\status.json'
    if (Test-Path -LiteralPath (Split-Path -Parent $bootstrapStatus)) {
        [IO.File]::WriteAllText($bootstrapStatus, (@{status='failed';phase='Startup failed';progress=0;error=$failureMessage} | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    }
    if ($NoBrowser -or -not $bootstrapOpened) { exit 1 }
    $retryFile = Join-Path $workspace '.manju\bootstrap\retry.request'
    while (!(Test-Path -LiteralPath $retryFile)) { Start-Sleep -Milliseconds 500 }
    Remove-Item -LiteralPath $retryFile
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
}
