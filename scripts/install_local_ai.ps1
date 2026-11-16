[CmdletBinding()]
param(
    [string]$ComfyDir,
    [string]$ModelsDir,
    [string]$RuntimeRoot,
    [ValidateSet('all','speech','lipsync')][string]$Components = 'all',
    [ValidateSet('auto','required','off')][string]$Emotion = 'auto',
    [switch]$CheckOnly,
    [switch]$StageOnly,
    [switch]$SmokeTest,
    [string]$ReferenceAudio,
    [string]$TestVideo
)
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
# A cmd launcher started by PowerShell 7 can inherit its incompatible module path.
# Use the built-in modules belonging to this PowerShell process.
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$projectRoot = Split-Path $PSScriptRoot -Parent
function Select-Directory([string]$Description) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $Description
    $dialog.ShowNewFolderButton = $false
    try {
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Folder selection cancelled.' }
        return $dialog.SelectedPath
    } finally { $dialog.Dispose() }
}
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    if (-not $ComfyDir) { $ComfyDir = Select-Directory 'Select ComfyUI (main.py) or ComfyUI_windows_portable' }
    if (-not $ModelsDir) { $ModelsDir = Select-Directory 'Select merged models folder (contains tts / lipsync / detection)' }
    if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $projectRoot '.manju\local-ai' }
    $RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
    $spec = Get-Content (Join-Path $PSScriptRoot 'local_ai\sources.json') -Raw | ConvertFrom-Json
    $bootstrapDir = Join-Path $RuntimeRoot 'bootstrap'
    New-Item -ItemType Directory -Force -Path $bootstrapDir | Out-Null
    # Exclusive handle prevents concurrent installers. The file can remain after a crash.
    $installLock = [IO.File]::Open((Join-Path $RuntimeRoot '.install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $archive = Join-Path $bootstrapDir 'uv.zip'
    if (!(Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.uv.sha256) {
        Write-Host 'Downloading the pinned uv installer...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $partial = $archive + '.partial'
        $webClient = New-Object Net.WebClient
        try { $webClient.DownloadFile($spec.uv.url, $partial) } finally { $webClient.Dispose() }
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.uv.sha256) { throw 'uv SHA256 verification failed.' }
        Move-Item -LiteralPath $partial -Destination $archive -Force
    }
    # Always extract from the verified archive, rather than trusting an old executable.
    Expand-Archive -LiteralPath $archive -DestinationPath $bootstrapDir -Force
    $uvExe = Join-Path $bootstrapDir 'uv.exe'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeRoot 'python'
    $env:UV_CACHE_DIR = Join-Path $RuntimeRoot 'cache\uv'
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
    $env:UV_NO_CONFIG = '1'
    $env:UV_NO_PROJECT = '1'
    $env:UV_LINK_MODE = 'copy'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:TEMP = Join-Path $RuntimeRoot 'tmp'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Force -Path $env:TEMP,$env:UV_CACHE_DIR | Out-Null
    Remove-Item Env:PYTHONPATH,Env:PYTHONHOME -ErrorAction SilentlyContinue
    & $uvExe python install $spec.python_version --no-bin --no-registry
    if ($LASTEXITCODE -ne 0) { throw 'Managed Python installation failed.' }
    $runtimePython = & $uvExe python find $spec.python_version
    if ($LASTEXITCODE -ne 0) { throw 'Managed Python was not found.' }
    $installerArgs = @('-I', '-X', 'utf8', '-u', (Join-Path $PSScriptRoot 'install_local_ai.py'), '--comfy', $ComfyDir, '--models-root', $ModelsDir, '--runtime-root', $RuntimeRoot, '--uv', $uvExe, '--components', $Components, '--emotion', $Emotion)
    if ($CheckOnly) { $installerArgs += '--check-only' }
    if ($StageOnly) { $installerArgs += '--stage-only' }
    & $runtimePython @installerArgs
    if ($LASTEXITCODE -ne 0) { throw "Installation or verification failed. Logs: $RuntimeRoot\logs" }
    if ($SmokeTest) {
        Write-Host 'Starting real GPU inference. Keep other GPU jobs stopped.'
        $smokeArgs = @('-I', '-X', 'utf8', '-u', (Join-Path $PSScriptRoot 'local_ai\smoke_test.py'), '--runtime-root', $RuntimeRoot, '--components', $Components)
        if ($ReferenceAudio) { $smokeArgs += @('--reference', $ReferenceAudio) }
        if ($TestVideo) { $smokeArgs += @('--video', $TestVideo) }
        & $runtimePython @smokeArgs
        if ($LASTEXITCODE -ne 0) { throw "Runtime installed but real inference failed. Logs: $RuntimeRoot\smoke" }
    }
    Write-Host "Completed. Reports: $RuntimeRoot\reports" -ForegroundColor Green
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($installLock) { $installLock.Dispose() }
}
