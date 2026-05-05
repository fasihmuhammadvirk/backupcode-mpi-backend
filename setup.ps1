#!/usr/bin/env pwsh
# =============================================================================
# MPI Backend - Automated Setup Script for Windows 
# =============================================================================

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "MPI Backend - Automated Setup" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""

# Check if uv is installed
Write-Host "Checking for uv..." -ForegroundColor Yellow
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile "$env:TEMP\uv-install.ps1"
        & "$env:TEMP\uv-install.ps1"
        
        # Refresh PATH to pick up uv
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        
        # Verify installation
        $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
        if ($uvCommand) {
            Write-Host "uv installed successfully!" -ForegroundColor Green
        } else {
            Write-Host "uv installation completed, but not found in PATH. You may need to restart PowerShell." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Failed to install uv. Please install manually." -ForegroundColor Red
        Write-Host "   Visit: https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Yellow
        Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
} else {
    try {
        $uvVersion = & uv --version
        Write-Host "uv is already installed: $uvVersion" -ForegroundColor Green
    } catch {
        Write-Host "uv found but version check failed" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Creating virtual environment..." -ForegroundColor Yellow
try {
    & uv venv
    Write-Host "Virtual environment created" -ForegroundColor Green
} catch {
    Write-Host "Failed to create virtual environment" -ForegroundColor Red
    Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Installing dependencies from lockfile..." -ForegroundColor Yellow
Write-Host "   This ensures everyone has the exact same package versions" -ForegroundColor Cyan
try {
    & uv sync --frozen
    Write-Host "Dependencies installed successfully" -ForegroundColor Green
} catch {
    Write-Host "Failed to install dependencies" -ForegroundColor Red
    Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "   Trying without --frozen flag..." -ForegroundColor Yellow
    try {
        & uv sync
        Write-Host "Dependencies installed (without frozen lockfile)" -ForegroundColor Green
    } catch {
        Write-Host "Failed to install dependencies even without --frozen" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Installing dbt packages..." -ForegroundColor Yellow
Write-Host "   (dbt_packages/ is gitignored and required for dbt runs)" -ForegroundColor Cyan
try {
    Push-Location mpi_analytics
    try {
        & uv run python run_dbt.py deps
        if ($LASTEXITCODE -ne 0) { throw "uv run python run_dbt.py deps exited with $LASTEXITCODE" }
        Write-Host "dbt packages installed successfully" -ForegroundColor Green
    } finally {
        Pop-Location
    }
} catch {
    Write-Host "Failed to install dbt packages" -ForegroundColor Red
    Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "   Aborting setup - fix the failure above, then retry with:" -ForegroundColor Yellow
    Write-Host "     Push-Location mpi_analytics; uv run python run_dbt.py deps; Pop-Location; .\setup.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Setting up environment file..." -ForegroundColor Yellow
if (-not (Test-Path .env)) {
    if (Test-Path .env.example) {
        Copy-Item .env.example .env
        Write-Host "Created .env from .env.example" -ForegroundColor Green
        Write-Host "Please edit .env with your configuration" -ForegroundColor Yellow
    } else {
        Write-Host "No .env.example found. Please create .env manually" -ForegroundColor Yellow
    }
} else {
    Write-Host ".env already exists" -ForegroundColor Green
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Configure your environment:" -ForegroundColor White
Write-Host "     notepad .env" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Run the application (uv will automatically use the virtual environment):" -ForegroundColor White
Write-Host "     uv run uvicorn mpi_backend.main:app --reload --host 0.0.0.0 --port 8000" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. Access the API at:" -ForegroundColor White
Write-Host "     http://localhost:8000" -ForegroundColor Gray
Write-Host ""
Write-Host "All team members will have the exact same environment!" -ForegroundColor Cyan
Write-Host ""