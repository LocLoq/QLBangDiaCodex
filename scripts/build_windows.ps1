param(
    [string]$Python = "C:\laragon\bin\python\python-3.13\python.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name NormaStore --paths src --hidden-import logging.config --add-data "alembic;alembic_migrations" --add-data "alembic.ini;." src\normastore\__main__.py
Write-Host "Đã tạo dist\NormaStore. Dùng installer\normastore.iss với Inno Setup để tạo installer."
