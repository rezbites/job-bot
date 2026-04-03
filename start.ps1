# Start the job bot (Windows PowerShell)
$ErrorActionPreference = "Stop"

# Activate venv
if (Test-Path ".venv\Scripts\Activate.ps1") {
    . .\.venv\Scripts\Activate.ps1
}

# Run the bot
python run_one.py
