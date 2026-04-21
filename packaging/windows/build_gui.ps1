param(
    [string]$PythonExe = "python",
    [switch]$Clean,
    [string]$DistPath = "",
    [string]$WorkPath = ""
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..\..")
$specPath = Join-Path $projectRoot "packaging\windows\ChatExportPDF.spec"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$buildDistPath = Join-Path $env:TEMP "ChatExportPDF-dist-$timestamp"

if (-not $DistPath) {
    $DistPath = Join-Path $projectRoot "dist\$timestamp"
}

if (-not $WorkPath) {
    $WorkPath = Join-Path $env:TEMP "ChatExportPDF-build-$timestamp"
}

Push-Location $projectRoot
try {
    $pyinstallerArgs = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", $buildDistPath,
        "--workpath", $WorkPath
    )
    if ($Clean) {
        $pyinstallerArgs += "--clean"
    }
    $pyinstallerArgs += $specPath

    Write-Host "Building standalone GUI from $specPath"
    Write-Host "Build dist path: $buildDistPath"
    Write-Host "Final dist path: $DistPath"
    Write-Host "Work path: $WorkPath"
    & $PythonExe @pyinstallerArgs

    $builtExePath = Join-Path $buildDistPath "ChatExportPDF.exe"
    if (-not (Test-Path $builtExePath)) {
        throw "Expected EXE was not created: $builtExePath"
    }

    New-Item -ItemType Directory -Force -Path $DistPath | Out-Null
    $finalExePath = Join-Path $DistPath "ChatExportPDF.exe"
    Copy-Item -LiteralPath $builtExePath -Destination $finalExePath -Force
    Write-Host "EXE path: $finalExePath"
}
finally {
    Pop-Location
}
