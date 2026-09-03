$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$minimumPythonVersion = [version]'3.10'
$venvDirectory = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venvDirectory 'Scripts\python.exe'

function Get-PythonVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$PrefixArguments = @()
    )

    try {
        $versionText = & $Command @PrefixArguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $versionText) {
            return $null
        }
        return [version]($versionText | Select-Object -Last 1)
    }
    catch {
        return $null
    }
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $basePython = $null
    $candidates = @(
        @{ Command = 'py'; Arguments = @('-3') },
        @{ Command = 'python'; Arguments = @() },
        @{ Command = 'python3'; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }
        $candidateVersion = Get-PythonVersion -Command $candidate.Command -PrefixArguments $candidate.Arguments
        if ($candidateVersion -and $candidateVersion -ge $minimumPythonVersion) {
            $basePython = $candidate
            break
        }
    }

    if (-not $basePython) {
        throw "Python 3.10 or newer was not found. Install Python and make the py, python, or python3 command available."
    }

    Write-Host "Creating .venv with Python $candidateVersion..."
    $basePythonCommand = [string]$basePython.Command
    $basePythonArguments = [string[]]$basePython.Arguments
    & $basePythonCommand @basePythonArguments -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Failed to create .venv. Make sure the Python venv module is available."
    }
}

$venvVersion = Get-PythonVersion -Command $venvPython
if (-not $venvVersion) {
    throw "Python in the project virtual environment cannot run: $venvPython. Delete .venv and run this script again."
}
if ($venvVersion -lt $minimumPythonVersion) {
    throw "The project virtual environment uses Python $venvVersion; Python $minimumPythonVersion or newer is required. Delete .venv and run this script again."
}

& $venvPython -c "import numpy, pyulog" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing dependencies into the project virtual environment...'
    & $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed. Check the network connection and requirements.txt."
    }
}

$appPort = 8765
if ($env:PX4_HEALTH_PORT) {
    $configuredPort = 0
    if (-not [int]::TryParse($env:PX4_HEALTH_PORT, [ref]$configuredPort) -or $configuredPort -lt 1 -or $configuredPort -gt 65535) {
        throw "PX4_HEALTH_PORT must be an integer from 1 through 65535."
    }
    $appPort = $configuredPort
}

$portProbe = New-Object System.Net.Sockets.TcpClient
$portInUse = $false
try {
    $portProbe.Connect([System.Net.IPAddress]::Loopback, $appPort)
    $portInUse = $true
}
catch [System.Net.Sockets.SocketException] {
    $portInUse = $false
}
finally {
    $portProbe.Dispose()
}

if ($portInUse) {
    $listenerPids = ''
    try {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $appPort -ErrorAction Stop)
        $listenerPids = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    }
    catch {
        # Looking up the PID may require additional permission; port detection does not.
    }
    $ownerText = if ($listenerPids) { " by PID $listenerPids" } else { '' }
    throw "Port $appPort is already in use$ownerText. Press Ctrl+C in the original terminal to stop the old service, then run this script again."
}

Write-Host "Starting the service with Python $venvVersion..."
& $venvPython (Join-Path $PSScriptRoot 'app.py')
