<#
.SYNOPSIS
    One-command local setup for Support Co-pilot (Windows).

.DESCRIPTION
    Creates the virtual environment, installs dependencies, sets up .env with
    your Groq API key, and offers to start the app - see docs/LOCAL_SETUP.md
    for what each step actually does and why.

.EXAMPLE
    .\setup.ps1
#>

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "    $msg" -ForegroundColor Red }

# ---------- 1. Check Python ----------
Write-Step "Checking Python"
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Err "Python not found on PATH."
    Write-Err "Install Python 3.10+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH' during install), then re-run this script."
    exit 1
}
$versionOutput = (& python --version 2>&1).ToString()
if ($versionOutput -match "Python (\d+)\.(\d+)") {
    $major = [int]$matches[1]
    $minor = [int]$matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Write-Err "Found $versionOutput, but Python 3.10 or newer is required."
        Write-Err "Install a newer version from https://www.python.org/downloads/."
        exit 1
    }
} else {
    Write-Warn "Could not parse '$versionOutput' - continuing anyway, but 3.10+ is required."
}
Write-Ok "$versionOutput found"

# ---------- 2. Create the virtual environment ----------
Write-Step "Setting up the virtual environment (.venv)"
if (Test-Path ".venv") {
    Write-Ok ".venv already exists - skipping creation"
} else {
    python -m venv .venv
    Write-Ok "Created .venv"
}

# ---------- 3. Install dependencies ----------
Write-Step "Installing dependencies (first run can take a few minutes)"
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
Write-Ok "Dependencies installed"

# ---------- 4. Configure .env ----------
Write-Step "Configuring .env"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Ok "Created .env from .env.example"
}

$envContent = Get-Content ".env" -Raw
$hasRealKey = $envContent -match 'GROQ_API_KEY=\s*gsk_[A-Za-z0-9_\-]+'

if (-not $hasRealKey) {
    Write-Host ""
    Write-Warn "A Groq API key is required - it's free at https://console.groq.com (sign up, then create an API key)."
    Write-Warn "Use your own key, not a teammate's - Groq's rate limits are per account."
    $plainKey = $null
    try {
        $secureKey = Read-Host "    Paste your Groq API key" -AsSecureString
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        $plainKey = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    } catch {
        Write-Warn "Couldn't read input interactively - skipping."
    }

    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        Write-Warn "No key entered - open .env yourself and set GROQ_API_KEY before running the app."
    } else {
        if ($envContent -match 'GROQ_API_KEY=.*') {
            $envContent = $envContent -replace 'GROQ_API_KEY=.*', "GROQ_API_KEY=$plainKey"
        } else {
            $envContent += "`nGROQ_API_KEY=$plainKey`n"
        }
        Set-Content -Path ".env" -Value $envContent -NoNewline
        Write-Ok "Saved to .env"
    }
} else {
    Write-Ok "GROQ_API_KEY already configured - leaving it as-is"
}

# ---------- 5. Done ----------
Write-Step "Setup complete"
Write-Host ""
Write-Host "Start the app any time with:" -ForegroundColor Cyan
Write-Host "    .venv\Scripts\python.exe -m uvicorn webapp.main:app --reload"
Write-Host ""
Write-Host "Then open http://127.0.0.1:8000 - first startup takes 10-20s longer (loading the embedding model)."
Write-Host "See demo/DEMO_SCRIPT.md for a ready-made first test."
Write-Host ""

try {
    $launch = Read-Host "Start it now? [y/N]"
} catch {
    $launch = "n"
}
if ($launch -match '^[Yy]') {
    & .venv\Scripts\python.exe -m uvicorn webapp.main:app --reload
}
