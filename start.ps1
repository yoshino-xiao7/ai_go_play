[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$DataDir,
    [string]$ConfigFile,
    [switch]$NoBrowser,
    [string]$ErrorLogPath
)

$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$serverPython = Join-Path $workspace '.venv\Scripts\pythonw.exe'
$url = "http://127.0.0.1:$Port"
$runtime = Join-Path $env:LOCALAPPDATA 'Manju\run'
$mutex = New-Object System.Threading.Mutex($false, "Local\Manju.Start.$Port")
$acquired = $false

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

try {
    try {
        $acquired = $mutex.WaitOne(30000)
    } catch [System.Threading.AbandonedMutexException] {
        $acquired = $true
    }
    if (-not $acquired) { throw 'Another startup is still running. Please retry in a moment.' }
    $health = Get-ManjuHealth
    if ($health) {
        Write-Host "Manju is running at $url"
        Write-Host "Storage: $($health.root)"
        if (-not $NoBrowser) { Start-Process $url }
        exit 0
    }
    if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $serverPython)) {
        throw "Python environment is missing. Run in '$workspace':`npy -3.12 -m venv .venv`n.\.venv\Scripts\python -m pip install -c requirements.lock -e '.[dev]'"
    }
    $dependencyCheck = @'
import sys
try:
    import manju.cli, fastapi, uvicorn, multipart, PIL, httpx, psutil, websocket
except ImportError:
    sys.exit(1)
'@
    & $python -c $dependencyCheck
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
    $arguments = @($serverPython, '-m', 'manju', 'serve', '--port', "$Port")
    if ($DataDir) { $arguments += @('--data-dir', $DataDir) }
    if ($ConfigFile) { $arguments += @('--config-file', $ConfigFile) }
    $defaultConfiguration = -not ($DataDir -or $ConfigFile -or $env:MANJU_DATA_DIR -or $env:MANJU_CONFIG_FILE)
    $anchorPath = Join-Path $workspace '.manju\launcher.json'
    $launcher = @'
import json
from pathlib import Path
import subprocess
import sys

settings = json.loads(sys.stdin.buffer.read())
try:
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
        $launchText = $launchSettings | ConvertTo-Json -Depth 4 -Compress | & $python -c $launcher
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
    if (-not $NoBrowser) { Start-Process $url }
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
    exit 1
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
