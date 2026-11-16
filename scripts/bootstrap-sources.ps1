$downloadConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\release\download-sources.json') -Raw | ConvertFrom-Json

function Get-ProjectMirror {
    $base = if ($env:MANJU_PROJECT_MIRROR) { $env:MANJU_PROJECT_MIRROR } else { $downloadConfig.project_mirror }
    if (!$base) { return }
    $parsed = [uri]$base
    if (!$parsed.IsAbsoluteUri -or $parsed.Scheme -ne 'https' -or !$parsed.Host -or $parsed.UserInfo -or $parsed.Query -or $parsed.Fragment) {
        throw 'MANJU_PROJECT_MIRROR must be an HTTPS base URL without credentials or query parameters.'
    }
    return $base.TrimEnd('/')
}

function Initialize-DownloadSource {
    if ($env:MANJU_DOWNLOAD_SOURCE -in @('china', 'overseas')) { return }
    $region = try {
        & "$env:SystemRoot\System32\curl.exe" -fsSL --max-time 3 'https://cloudflare.com/cdn-cgi/trace' 2>$null |
            Where-Object { $_ -match '^loc=[A-Z]{2}$' } | Select-Object -First 1
    } catch {}
    if ($region) {
        $env:MANJU_DOWNLOAD_SOURCE = if ($region -eq 'loc=CN') { 'china' } else { 'overseas' }
    } else {
        $location = try { (Get-WinHomeLocation).GeoId } catch { $null }
        $env:MANJU_DOWNLOAD_SOURCE = if ($location -eq 45) { 'china' } else { 'overseas' }
    }
}

function Invoke-DownloadCommand([string]$Executable, [string[]]$Arguments) {
    # Windows PowerShell wraps native stderr as ErrorRecords even for successful downloads.
    $ErrorActionPreference = 'Continue'
    $output = & $Executable @Arguments 2>&1
    return @{code=$LASTEXITCODE; output=(($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine)}
}

function Get-PinnedUv($spec, [string]$directory, [scriptblock]$report) {
    $wheel = $downloadConfig.uv_wheel
    $official = @{url=$spec.url; hash=$spec.sha256; archive='uv.zip'; entry='uv.exe'}
    $public = @{url=$wheel.mirror; hash=$wheel.sha256; archive='uv-wheel.zip'; entry=$wheel.executable}
    $base = Get-ProjectMirror
    $own = @()
    if ($base) {
        $name = ([uri]$spec.url).Segments[-1]
        $own = @(@{url="$base/artifacts/$($spec.sha256)/$name"; hash=$spec.sha256; archive='uv.zip'; entry='uv.exe'})
    }
    $sources = if ($env:MANJU_DOWNLOAD_SOURCE -eq 'china') { @($public) + $own + @($official) } else { @($official, $public) + $own }
    $failures = @()
    foreach ($source in $sources) {
        $cache = Join-Path $directory $source.archive
        if ((Test-Path -LiteralPath $cache) -and (Get-FileHash -LiteralPath $cache -Algorithm SHA256).Hash -eq $source.hash) {
            $choice = $source
            break
        }
    }
    if (!$choice) {
        foreach ($source in $sources) {
            $hostName = ([uri]$source.url).Host
            & $report "uv: $hostName"
            $cache = Join-Path $directory $source.archive
            $partial = "$cache.$([guid]::NewGuid().ToString('N')).partial"
            try {
                $result = Invoke-DownloadCommand "$env:SystemRoot\System32\curl.exe" @(
                    '-fLsS', '--connect-timeout', '8', '--max-time', '180', '--speed-time', '20',
                    '--speed-limit', '1024', '-o', $partial, $source.url)
                if ($result.code -ne 0) { throw $result.output }
                if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $source.hash) { throw 'SHA-256 mismatch' }
                Move-Item -LiteralPath $partial -Destination $cache -Force
                $choice = $source
                break
            } catch { $failures += "${hostName}: $($_.Exception.Message)" }
            finally { if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force } }
        }
    }
    if (!$choice) { throw ("uv download failed.`n" + ($failures -join "`n")) }
    $temporary = Join-Path $directory ('uv-' + [guid]::NewGuid().ToString('N') + '.partial')
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead((Join-Path $directory $choice.archive))
    try {
        $entry = $archive.GetEntry($choice.entry)
        if (!$entry) { throw 'Verified uv archive did not contain its expected executable.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $temporary)
        $executable = Join-Path $directory 'uv.exe'
        Move-Item -LiteralPath $temporary -Destination $executable -Force
        return $executable
    } finally {
        $archive.Dispose()
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Install-ManagedPython([string]$Uv, [string]$Version, [scriptblock]$report) {
    $base = Get-ProjectMirror
    $official = 'https://releases.astral.sh/github/python-build-standalone/releases/download'
    $github = 'https://github.com/astral-sh/python-build-standalone/releases/download'
    $domestic = $downloadConfig.china.python
    $own = if ($base) { @("$base/python-build-standalone") } else { @() }
    $sources = if ($env:MANJU_DOWNLOAD_SOURCE -eq 'china') { @($domestic) + $own + @($official, $github) } else { @($official, $github, $domestic) + $own }
    $previous = $env:UV_PYTHON_INSTALL_MIRROR
    $previousTimeout = $env:UV_HTTP_TIMEOUT
    $previousRetries = $env:UV_HTTP_RETRIES
    try {
        $env:UV_HTTP_TIMEOUT = '30'
        $env:UV_HTTP_RETRIES = '1'
        $failures = @()
        foreach ($mirror in $sources) {
            $hostName = ([uri]$mirror).Host
            & $report "Python: $hostName"
            $env:UV_PYTHON_INSTALL_MIRROR = $mirror
            $result = Invoke-DownloadCommand $Uv @('python', 'install', $Version, '--no-bin', '--no-registry')
            if ($result.code -eq 0) {
                $python = Invoke-DownloadCommand $Uv @('python', 'find', $Version)
                if ($python.code -ne 0) { throw 'Managed Python was not found.' }
                return $python.output.Trim()
            }
            $failures += "${hostName}: $($result.output)"
        }
        throw ("Python download failed.`n" + ($failures -join "`n"))
    } finally {
        $env:UV_PYTHON_INSTALL_MIRROR = $previous
        $env:UV_HTTP_TIMEOUT = $previousTimeout
        $env:UV_HTTP_RETRIES = $previousRetries
    }
}
