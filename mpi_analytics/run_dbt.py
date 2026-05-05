import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

# Resolve the path from the current folder, one up, where we store the project's .env
dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

dbt_cmd = os.getenv("DBT_COMMAND", "dbt")

# Get command-line arguments (excluding the script name)
args = sys.argv[1:]

# If no arguments provided, default to 'run'
if not args:
    args = ["run", "--no-partial-parse"]

# Build the full command
cmd_list = [dbt_cmd] + args

subprocess.run(cmd_list, shell=False, check=True)
