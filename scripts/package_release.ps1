[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$VersionTag,
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($VersionTag -notmatch '^v\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$') {
    throw "VersionTag must use a semantic version such as v1.2.0 or v1.3.0-beta.1: $VersionTag"
}

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$portableDirectory = Join-Path $projectRoot 'dist\PX4-Log-Health-Checker'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot 'release'
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

if (-not $OutputDirectory.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release output directory must be inside the project directory: $projectRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $portableDirectory 'PX4-Log-Health-Checker.exe') -PathType Leaf)) {
    throw "Windows portable package was not found. Run .\scripts\build_windows.ps1 first."
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$archiveName = "PX4-Log-Health-Checker-$VersionTag-win64.zip"
$archivePath = Join-Path $OutputDirectory $archiveName
$checksumPath = "$archivePath.sha256"

Compress-Archive `
    -LiteralPath $portableDirectory `
    -DestinationPath $archivePath `
    -CompressionLevel Optimal `
    -Force

$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$hash  $archiveName" -Encoding Ascii

Write-Host "Release archive: $archivePath"
Write-Host "SHA-256 file:   $checksumPath"
