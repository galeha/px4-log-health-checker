[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipSmokeTest,
    [string]$PythonPath = ""
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$defaultVenvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$requirements = Join-Path $projectRoot 'requirements-build.txt'
$specFile = Join-Path $projectRoot 'packaging\px4-log-health-checker.spec'
$executable = Join-Path $projectRoot 'dist\PX4-Log-Health-Checker\PX4-Log-Health-Checker.exe'

Set-Location -LiteralPath $projectRoot

if ($PythonPath) {
    $pythonExecutable = [IO.Path]::GetFullPath($PythonPath)
}
else {
    $pythonExecutable = $defaultVenvPython
}

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Python was not found at $pythonExecutable. Run .\run.ps1 once to create the project virtual environment, or pass -PythonPath."
}

& $pythonExecutable -c "import importlib.metadata, numpy, pyulog; assert importlib.metadata.version('pyinstaller') == '6.22.2'" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing pinned build dependencies...'
    & $pythonExecutable -m pip install --disable-pip-version-check --requirement $requirements
    if ($LASTEXITCODE -ne 0) {
        throw 'Installing build dependencies failed.'
    }
}
else {
    Write-Host 'Pinned build dependencies are already installed.'
}

if (-not $SkipTests) {
    Write-Host 'Running source tests...'
    & $pythonExecutable -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        throw 'Source tests failed; packaging was stopped.'
    }
}

Write-Host 'Building the Windows onedir package...'
& $pythonExecutable -m PyInstaller --noconfirm --clean $specFile
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'PyInstaller did not produce the expected executable.'
}

if (-not $SkipSmokeTest) {
    Write-Host 'Running packaged application smoke test...'
    & (Join-Path $PSScriptRoot 'smoke_test_packaged_app.ps1') -ExecutablePath $executable
    if ($LASTEXITCODE -ne 0) {
        throw 'Packaged application smoke test failed.'
    }
}

Write-Host ''
Write-Host 'Windows portable package is ready:'
Write-Host (Split-Path -Parent $executable)
