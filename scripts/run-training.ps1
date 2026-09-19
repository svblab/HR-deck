# Запуск локальной версии с учебной базой (миграции 1–15, EPIC-024/025/026).
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $repoRoot "src"
$env:PERSONNEL_AVAILABILITY_DATA = Join-Path $env:USERPROFILE ".local\share\personnel-availability-training"
Set-Location $repoRoot
python -m ui
