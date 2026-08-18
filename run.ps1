$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

python -c "import numpy, pyulog" 2>$null
if ($LASTEXITCODE -ne 0) {
    python -m pip install -r requirements.txt
}

python app.py
