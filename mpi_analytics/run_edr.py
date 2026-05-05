import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

edr_cmd = os.getenv("EDR_COMMAND", "edr")

args = sys.argv[1:]

if not args:
    args = ["send-report"]

cmd_list = [edr_cmd] + args

subprocess.run(cmd_list, shell=False, check=True)
