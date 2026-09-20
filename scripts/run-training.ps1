# UX test launcher. Data: %USERPROFILE%\.local\share\personnel-availability-ux-test
# After -Clean setup: admin / 111. Migrations 1-17 (ADR-0011).
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $env:USERPROFILE ".local\share\personnel-availability-ux-test"

$env:PYTHONPATH = Join-Path $repoRoot "src"
$env:PERSONNEL_AVAILABILITY_DATA = $dataDir

function Resolve-PythonExe {
    $candidates = @()
    foreach ($name in @("python", "python3", "py")) {
        $cmds = Get-Command $name -All -ErrorAction SilentlyContinue
        if ($cmds) {
            $candidates += $cmds | ForEach-Object { $_.Source }
        }
    }
    $candidates += @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) {
            continue
        }
        if ($candidate -like "*\WindowsApps\*") {
            continue
        }
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }
    throw "Python 3.11+ not found in PATH."
}

if ($Clean) {
    if (Test-Path -LiteralPath $dataDir) {
        Remove-Item -LiteralPath $dataDir -Recurse -Force
        Write-Host "Removed data directory: $dataDir"
    } else {
        Write-Host "Data directory not found (already clean): $dataDir"
    }
    Write-Host "Run without -Clean to start SetupDialog (admin / 111)."
    exit 0
}

$python = Resolve-PythonExe
Write-Host "Python: $python"
Write-Host "Data: $dataDir"
Write-Host "UX login: admin / 111 (after SetupDialog)"

Set-Location $repoRoot
try {
    & $python -m ui
    if ($LASTEXITCODE -ne 0) {
        throw "Application exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host ""
    Write-Host "STARTUP ERROR: $_" -ForegroundColor Red
    Write-Host "Check Python, PySide6, sqlcipher3, and the data directory."
    Read-Host "Press Enter to close"
    exit 1
}
