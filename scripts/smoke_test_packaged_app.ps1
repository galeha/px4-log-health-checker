[CmdletBinding()]
param(
    [string]$ExecutablePath = "",
    [int]$StartupTimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $ExecutablePath) {
    $ExecutablePath = Join-Path $projectRoot 'dist\PX4-Log-Health-Checker\PX4-Log-Health-Checker.exe'
}
$ExecutablePath = [IO.Path]::GetFullPath($ExecutablePath)

if (-not $ExecutablePath.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The packaged executable must be inside the project directory: $projectRoot"
}
if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Packaged executable was not found: $ExecutablePath"
}
if ($StartupTimeoutSeconds -lt 1 -or $StartupTimeoutSeconds -gt 300) {
    throw 'StartupTimeoutSeconds must be from 1 through 300.'
}

$portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$portProbe.Start()
$port = ([System.Net.IPEndPoint]$portProbe.LocalEndpoint).Port
$portProbe.Stop()

$logDirectory = Join-Path $projectRoot 'build\smoke-test'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$stdoutPath = Join-Path $logDirectory 'packaged-app.stdout.log'
$stderrPath = Join-Path $logDirectory 'packaged-app.stderr.log'

$previousPort = $env:PX4_HEALTH_PORT
$previousNoBrowser = $env:PX4_HEALTH_NO_BROWSER
$process = $null

try {
    $env:PX4_HEALTH_PORT = [string]$port
    $env:PX4_HEALTH_NO_BROWSER = '1'
    $process = Start-Process `
        -FilePath $ExecutablePath `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    $health = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) {
            break
        }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 2
            if ($health.ok -eq $true) {
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }

    if (-not $health -or $health.ok -ne $true) {
        $process.Refresh()
        $exitDescription = if ($process.HasExited) { "process exited with code $($process.ExitCode)" } else { 'startup timed out' }
        throw "Packaged application health check failed: $exitDescription. Logs: $logDirectory"
    }

    $indexResponse = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 5
    if ($indexResponse.StatusCode -ne 200 -or $indexResponse.Content -notmatch 'id="uploadPanel"') {
        throw "Packaged application did not serve the expected frontend. Logs: $logDirectory"
    }

    Write-Host "Packaged application smoke test passed on port $port."
}
finally {
    if ($process) {
        $process.Refresh()
        if (-not $process.HasExited) {
            try {
                Invoke-RestMethod `
                    -Uri "http://127.0.0.1:$port/api/shutdown" `
                    -Method Post `
                    -Headers @{ 'X-PX4-Health-Client' = 'browser' } `
                    -TimeoutSec 2 | Out-Null
            }
            catch {
                # Fall back to stopping the test process below.
            }
            if (-not $process.WaitForExit(5000)) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                $process.WaitForExit(5000) | Out-Null
            }
        }
        $process.Dispose()
    }

    $env:PX4_HEALTH_PORT = $previousPort
    $env:PX4_HEALTH_NO_BROWSER = $previousNoBrowser
}
