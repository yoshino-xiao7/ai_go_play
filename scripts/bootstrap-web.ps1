param([string]$StateDir, [string]$PagePath, [string]$Token)
$ErrorActionPreference = 'Stop'
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
[IO.File]::WriteAllText((Join-Path $StateDir 'web.json'), (@{port=$port;token=$Token;pid=$PID} | ConvertTo-Json), [Text.Encoding]::UTF8)
$started = Get-Date
$finished = $null
try {
    while (((Get-Date) - $started).TotalHours -lt 6) {
        if ($finished -and ((Get-Date) - $finished).TotalSeconds -gt 15) { break }
        if (!$listener.Pending()) { Start-Sleep -Milliseconds 80; continue }
        $client = $listener.AcceptTcpClient()
        try {
            $client.ReceiveTimeout = 2500
            $stream = $client.GetStream()
            $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::ASCII, $false, 1024, $true)
            $first = $reader.ReadLine()
            if (!$first) { continue }
            $parts = $first.Split(' ')
            $headers = @{}
            for ($i=0; $i -lt 64; $i++) {
                $line = $reader.ReadLine()
                if (!$line) { break }
                $separator = $line.IndexOf(':')
                if ($separator -gt 0) { $headers[$line.Substring(0, $separator).ToLowerInvariant()] = $line.Substring($separator + 1).Trim() }
            }
            $url = "http://127.0.0.1:$port"
            $valid = ($headers['host'] -eq "127.0.0.1:$port") -and (!$headers['origin'] -or $headers['origin'] -eq $url) -and ($headers['sec-fetch-site'] -ne 'cross-site')
            $status = '200 OK'; $type = 'application/json; charset=utf-8'; $body = '{}'
            if (!$valid) { $status = '403 Forbidden' }
            elseif ($parts[0] -eq 'GET' -and $parts[1] -eq '/') {
                $type = 'text/html; charset=utf-8'
                $body = [IO.File]::ReadAllText($PagePath).Replace('__RETRY_TOKEN__', $Token)
            } elseif ($parts[0] -eq 'GET' -and $parts[1] -eq '/status') {
                try { $body = [IO.File]::ReadAllText((Join-Path $StateDir 'status.json')) } catch { $body = '{"phase":"正在准备启动","status":"running","progress":0}' }
            } elseif ($parts[0] -eq 'POST' -and $parts[1] -eq "/retry/$Token") {
                [IO.File]::WriteAllText((Join-Path $StateDir 'retry.request'), 'retry')
            } else { $status = '404 Not Found' }
            $bytes = [Text.Encoding]::UTF8.GetBytes($body)
            $head = [Text.Encoding]::ASCII.GetBytes("HTTP/1.1 $status`r`nContent-Type: $type`r`nContent-Length: $($bytes.Length)`r`nCache-Control: no-store`r`nX-Content-Type-Options: nosniff`r`nConnection: close`r`n`r`n")
            $stream.Write($head, 0, $head.Length)
            $stream.Write($bytes, 0, $bytes.Length)
            if ($body -match '"status"\s*:\s*"ready"') { if (!$finished) { $finished = Get-Date } }
            if ($finished -and ((Get-Date) - $finished).TotalSeconds -gt 15) { break }
        } catch {
            [IO.File]::AppendAllText((Join-Path $StateDir 'web-errors.log'), ($_.Exception.Message + [Environment]::NewLine))
        } finally { $client.Dispose() }
    }
} finally { $listener.Stop() }
