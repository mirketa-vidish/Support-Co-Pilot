# Local Setup Guide — Elixir Support Triage

For anyone setting this project up on their own machine to test it. About 10 minutes,
including the one-time model download.

**Important**: each tester runs their **own local copy** with their **own Groq API key**. Nobody's
projects/cases are shared with anyone else's instance — if you want a shared, everyone-sees-the-
same-data setup instead, that's a different (deployment) conversation, not this guide.

---

## Prerequisites

- **Python 3.10 or newer** — check with `python --version`. ([python.org/downloads](https://www.python.org/downloads/))
- **Git** — check with `git --version`. ([git-scm.com](https://git-scm.com/downloads))
- A free **Groq account** for the LLM — sign up at [console.groq.com](https://console.groq.com).
  Each person needs their **own** API key, not a shared one — Groq's free tier has per-account
  rate limits, and multiple people sharing one key will exhaust it quickly (we hit this
  ourselves during development).

---

## Step 1 — Get the code

```powershell
git clone https://github.com/VidishSharma1/Support-Co-Pilot.git
cd Support-Co-Pilot
```

## Step 2 — Create an isolated Python environment and install dependencies

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Mac/Linux:**
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

This downloads FastAPI, ChromaDB, the Groq client, sentence-transformers, etc. into a folder
(`.venv/`) private to this project — it won't affect Python anywhere else on your machine.

## Step 3 — Get a Groq API key

1. Go to [console.groq.com](https://console.groq.com), sign up (free).
2. Create an API key.
3. Keep it handy for the next step.

## Step 4 — Configure your environment file

**Windows:**
```powershell
copy .env.example .env
```
**Mac/Linux:**
```bash
cp .env.example .env
```

Open the new `.env` file in any text editor and paste your key in:
```
GROQ_API_KEY=gsk_your_own_key_here
```
Everything else in `.env` already has a working default — leave it as-is unless you have a
specific reason to change it.

## Step 5 — Run it

**Windows:**
```powershell
.venv\Scripts\python.exe -m uvicorn webapp.main:app --reload
```
**Mac/Linux:**
```bash
.venv/bin/python -m uvicorn webapp.main:app --reload
```

Wait for `Uvicorn running on http://127.0.0.1:8000` — the **first** startup takes 10-20 seconds
longer than usual, since it's loading the embedding model into memory. Then open
`http://127.0.0.1:8000` in a browser.

The very first time you run it, it also downloads a small (~90 MB) embedding model from
HuggingFace — this needs internet access once; after that it runs fully offline.

## Step 6 — Try it

The `demo/` folder has a ready-made example (a design doc, zipped SFDX code, repro steps, and a
debug log) with a full walkthrough in `demo/DEMO_SCRIPT.md` — follow that to create your first
project and case, and see a real investigation run end to end.

If you want to understand *how* any of it works under the hood, `docs/IMPLEMENTATION_GUIDE.md` is
a from-zero explanation of every file and concept in the project.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `RuntimeError: Missing required environment variable: GROQ_API_KEY` | `.env` doesn't exist yet, or is missing the key, or you're running the command from a different folder than the project root. |
| Page won't load / connection refused | Give it the extra 10-20s on first startup. If it still fails, check the terminal running uvicorn for an actual error message. |
| `[Errno 48] Address already in use` / port 8000 busy | Something else (maybe another instance of this app) is already using port 8000. Either stop that, or run this one on a different port: add `--port 8001` to the uvicorn command and use that URL instead. |
| Investigation is slow, or errors mentioning "rate limit" | Groq's free tier throttles requests per minute/day. This is expected occasionally, not a bug — wait a bit and retry. |
| "Project already exists" when creating one | Someone (maybe you, in an earlier test) already created a project with that exact name in *your* local copy. Pick a different name, or open that existing project instead. |
