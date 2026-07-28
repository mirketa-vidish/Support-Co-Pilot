#!/usr/bin/env bash
# One-command local setup for Support Co-pilot (Mac/Linux).
# Creates the virtual environment, installs dependencies, sets up .env with
# your Groq API key, and offers to start the app - see docs/LOCAL_SETUP.md
# for what each step actually does and why.
#
# Usage: ./setup.sh
set -euo pipefail

step() { printf "\n==> %s\n" "$1"; }
ok()   { printf "    \033[32m%s\033[0m\n" "$1"; }
warn() { printf "    \033[33m%s\033[0m\n" "$1"; }
err()  { printf "    \033[31m%s\033[0m\n" "$1" >&2; }

# ---------- 1. Check Python ----------
step "Checking Python"
PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    err "Python not found on PATH."
    err "Install Python 3.10+ from https://www.python.org/downloads/, then re-run this script."
    exit 1
fi

PY_VERSION=$("$PYTHON_BIN" --version 2>&1)
PY_MAJOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info[0])")
PY_MINOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info[1])")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    err "Found $PY_VERSION, but Python 3.10 or newer is required."
    err "Install a newer version from https://www.python.org/downloads/."
    exit 1
fi
ok "$PY_VERSION found"

# ---------- 2. Create the virtual environment ----------
step "Setting up the virtual environment (.venv)"
if [ -d ".venv" ]; then
    ok ".venv already exists - skipping creation"
else
    "$PYTHON_BIN" -m venv .venv
    ok "Created .venv"
fi

# ---------- 3. Install dependencies ----------
step "Installing dependencies (first run can take a few minutes)"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
ok "Dependencies installed"

# ---------- 4. Configure .env ----------
step "Configuring .env"
if [ ! -f ".env" ]; then
    cp .env.example .env
    ok "Created .env from .env.example"
fi

if ! grep -Eq '^GROQ_API_KEY=gsk_[A-Za-z0-9_-]+' .env; then
    echo ""
    warn "A Groq API key is required - it's free at https://console.groq.com (sign up, then create an API key)."
    warn "Use your own key, not a teammate's - Groq's rate limits are per account."
    read -rsp "    Paste your Groq API key: " GROQ_KEY
    echo ""
    if [ -z "$GROQ_KEY" ]; then
        warn "No key entered - edit .env yourself and set GROQ_API_KEY before running the app."
    else
        if grep -q '^GROQ_API_KEY=' .env; then
            # -i.bak works on both GNU sed (Linux) and BSD sed (macOS)
            sed -i.bak "s|^GROQ_API_KEY=.*|GROQ_API_KEY=$GROQ_KEY|" .env && rm -f .env.bak
        else
            printf "\nGROQ_API_KEY=%s\n" "$GROQ_KEY" >> .env
        fi
        ok "Saved to .env"
    fi
else
    ok "GROQ_API_KEY already configured - leaving it as-is"
fi

# ---------- 5. Done ----------
step "Setup complete"
echo ""
echo "Start the app any time with:"
echo "    .venv/bin/python -m uvicorn webapp.main:app --reload"
echo ""
echo "Then open http://127.0.0.1:8000 - first startup takes 10-20s longer (loading the embedding model)."
echo "See demo/DEMO_SCRIPT.md for a ready-made first test."
echo ""

read -rp "Start it now? [y/N] " LAUNCH
if [[ "$LAUNCH" =~ ^[Yy]$ ]]; then
    .venv/bin/python -m uvicorn webapp.main:app --reload
fi
