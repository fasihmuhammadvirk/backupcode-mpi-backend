#!/bin/bash
# =============================================================================
# MPI Backend - Automated Setup Script for Linux/Mac
# =============================================================================

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║           MPI Backend - Automated Setup                    ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check if uv is installed
echo "🔍 Checking for uv..."
if ! command -v uv &> /dev/null; then
    echo "  Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Add uv to PATH for current session
    export PATH="$HOME/.cargo/bin:$PATH"
    
    if command -v uv &> /dev/null; then
        echo "  uv installed successfully!"
    else
        echo "  Failed to install uv. Please install manually."
        echo "   Visit: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
else
    UV_VERSION=$(uv --version)
    echo "  uv is already installed: $UV_VERSION"
fi

echo ""
echo "  Creating virtual environment..."
if uv venv; then
    echo "  Virtual environment created"
else
    echo "  Failed to create virtual environment"
    exit 1
fi

echo ""
echo "  Installing dependencies from lockfile..."
echo "   This ensures everyone has the exact same package versions"
if uv sync --frozen; then
    echo "  Dependencies installed successfully"
else
    echo "  Failed to install dependencies"
    echo "   Trying without --frozen flag..."
    if uv sync; then
        echo "  Dependencies installed (without frozen lockfile)"
    else
        echo "  Failed to install dependencies even without --frozen"
        exit 1
    fi
fi

echo ""
echo "  Installing dbt packages..."
echo "   (dbt_packages/ is gitignored and required for dbt runs)"
if (cd mpi_analytics && uv run python run_dbt.py deps); then
    echo "  dbt packages installed successfully"
else
    echo "  Failed to install dbt packages"
    echo "   Aborting setup — fix the failure above, then retry with:"
    echo "     (cd mpi_analytics && uv run python run_dbt.py deps) && ./setup.sh"
    exit 1
fi

echo ""
echo "  Setting up environment file..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "  Created .env from .env.example"
        echo "   Please edit .env with your configuration"
    else
        echo "   No .env.example found. Please create .env manually"
    fi
else
    echo "  .env already exists"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                Setup Complete!                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "  Next Steps:"
echo ""
echo "  1. Configure your environment:"
echo "     nano .env"
echo ""
echo "  2. Run the application (uv will automatically use the virtual environment):"
echo "     uv run uvicorn mpi_backend.main:app --reload --host 0.0.0.0 --port 8000"
echo ""
echo "  3. Access the API at:"
echo "     http://localhost:8000"
echo ""
echo "  Tip: All team members will have the exact same environment!"
echo ""