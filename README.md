# Support Co-pilot - RAG + LLM

An MCP server that turns a customer's Elixir implementation (SFDX code +
Solution Design Document) plus each support case's inputs (repro steps,
FINEST debug log) into a searchable knowledge base, plus an LLM agent
(Groq-hosted, tool-calling) that investigates a case and classifies the root
cause as an **Implementation Gap**, a **Data Issue**, or a genuine
**Product Bug** in the Elixir package.

> **New here?** Clone this repo, then run `.\setup.ps1` (Windows) or `./setup.sh` (Mac/Linux) —
> it handles the whole local setup for you. [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md) covers
> what it's doing and how to do it by hand. [`docs/IMPLEMENTATION_GUIDE.md`](docs/IMPLEMENTATION_GUIDE.md)
> explains how every part of it works, assuming no prior knowledge. `demo/` has a ready-made
> example case to try first.

## Project / case model

Two levels, and this split is deliberate:

- **Project** (one per customer): owns the SFDX code and the SDD. There is
  exactly **one current copy** of each, ever - code is replaced in place via
  an explicit "update code" action when a fix lands, never re-uploaded per
  case. This is what stops the agent from ever mixing up which code belongs
  to which case, or reasoning against a stale copy from a case opened months
  ago.
- **Case** (many per project): just a case ID, an optional repro-steps file,
  and a required FINEST debug log. Every case under a project automatically
  shares that project's current code and SDD - nothing case-specific to
  upload for either.

The anti-hallucination guarantee goes further than "the data is organized
this way": in `elixir_rag/agent_core.py`, `project_id` (and, once known,
`case_id`) is bound into the tool functions the LLM calls *before* the model
ever sees a tool schema - `project_id` is never a parameter the model can
set. It's not a prompt instruction the model could get wrong; it's not a
choice available to it at all.

## Architecture

```
ingest.py  -->  parses SDD/code/repro/log  -->  chromadb (persistent, local)
                                                        |
webapp/main.py (FastAPI)  --calls-->  elixir_rag/agent_core.py --queries--> chromadb
agent.py (CLI)             --calls-->        |
                                              | Groq tool-calling      local sentence-transformers
                                              v                        embeddings (offline)
                                          Groq API

elixir_rag/server.py (MCP server, stdio) also exposes the same tools for external MCP clients.
```

- `elixir_rag/parsers/` - one parser per input type:
  - `docx_parser.py` - Solution Design Document (Word), heading-aware chunking.
  - `code_parser.py` - SFDX project (walks `force-app`, respects `package.xml`), one file per chunk group.
  - `text_parser.py` - issue replication steps (markdown/text).
  - `log_parser.py` - FINEST debug log: `chunk_debug_log` for semantic search, plus
    `extract_log_signals` - a purpose-built regex pass that pulls out exceptions,
    fatal errors, DML/SOQL counts, and governor limit usage into a compact summary,
    instead of dumping raw log text at the LLM (a 50k-line log will blow context and
    bury the signal - same lesson as `get_pipeline_summary` in the prior project).
- `elixir_rag/vector_store.py` - persistent, project-scoped Chroma collection. `sdd`/`code`
  chunks are tagged with `project_id` only; `repro_steps`/`debug_log` chunks are additionally
  tagged with `case_id`. `project_data/<project_id>/code/` and
  `project_data/<project_id>/cases/<case_id>/debug_log.log` hold the raw files on disk.
- `elixir_rag/tools.py` - the 6 tool implementations (`list_projects`, `list_cases`,
  `search_documents`, `extract_log_signals`, `list_code_files`, `get_file_content`), shared by
  the MCP server and any other in-process caller.
- `elixir_rag/server.py` - MCP server exposing `elixir_rag/tools.py`'s functions over stdio,
  for external MCP clients (Claude Desktop, etc). Since project_id isn't bound for external
  clients, they must supply it on every call.
- `elixir_rag/agent_core.py` - the Groq tool-calling loop itself (`investigate()`), scoped to
  one project (and optionally one case) per call. Shared by `agent.py` (CLI) and
  `webapp/main.py` (web UI).
- `ingest.py` - importable functions (`create_project`, `set_project_code`, `set_project_sdd`,
  `create_case`) plus a CLI wrapper around them; used directly by the web UI's endpoints.
- `agent.py` - terminal REPL wrapper around `elixir_rag/agent_core.py`.
- `webapp/` - FastAPI + vanilla-JS web UI (see below), the recommended way to use this.

## 1. Install dependencies

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The first run of the embedding model will download `all-MiniLM-L6-v2` (~90MB)
from HuggingFace once; after that it runs fully offline, no API key needed
for embeddings.

## 2. Configure environment

```powershell
copy .env.example .env
```

Fill in `GROQ_API_KEY` (free at console.groq.com). Everything else has a
sensible default.

## 3. Generate the synthetic sample case (optional, for testing)

A fabricated case, `CASE-1001`, lives under `sample_cases/CASE-1001/` -
repro steps, code, and debug log are already plain text/code files; the SDD
needs to be generated as a real `.docx`:

```powershell
.venv\Scripts\python.exe scripts\generate_sample_sdd.py
```

The scenario: a customer's custom trigger handler was supposed to (per its
SDD) skip a duplicate-check and flag the record for manual review when
Insurance ID is blank - but that null-check was never implemented, so a
`NullPointerException` is thrown instead. This is a textbook **Implementation
Gap**: the base Elixir package method's contract (documented in the SDD's
"Known Limitations" section) explicitly makes null-checking the caller's
responsibility, so the base package is working exactly as designed.

## 4. Create a project, then a case

```powershell
.venv\Scripts\python.exe ingest.py create-project --project-id "Meridian Health Partners" `
    --sdd sample_cases\CASE-1001\SDD.docx --code sample_cases\CASE-1001\code

.venv\Scripts\python.exe ingest.py create-case --project-id "Meridian Health Partners" `
    --case-id CASE-1001 --log sample_cases\CASE-1001\debug_log.log `
    --repro sample_cases\CASE-1001\repro_steps.md
```

Once a fix lands and the code needs to change, replace it in place (this
never touches existing cases' repro steps/logs):

```powershell
.venv\Scripts\python.exe ingest.py update-project-code --project-id "Meridian Health Partners" `
    --code path\to\fixed\force-app --confirm-override
```

`create-case` is a no-op if the case ID already exists unless you pass `--force`.

## 5. Run the agent

Single question:
```powershell
.venv\Scripts\python.exe agent.py --project-id "Meridian Health Partners" --case-id CASE-1001 "Investigate and tell me the root cause."
```

Interactive (prompts for a project if `--project-id` is omitted; type `switch` to change projects):
```powershell
.venv\Scripts\python.exe agent.py
```

Watch `elixir_rag.log` in a second window to see every tool call as it fires:
```powershell
Get-Content elixir_rag.log -Wait -Tail 20
```

## 6. Or, run the web UI instead (recommended)

```powershell
.venv\Scripts\python.exe -m uvicorn webapp.main:app --reload
```

Then open http://127.0.0.1:8000. The first screen is **Projects**:

- **Projects** (landing screen) - every project as a card; **+ New Project** uploads the SFDX
  code (`.zip`, required, must contain `package.xml` somewhere inside) and, optionally, the SDD
  (`.docx`).
- Inside a project:
  - **Overview** - code file browser, chunk counts, and **Update code** / **Update SDD** actions.
    Replacing code requires checking "I understand this replaces the existing code" - it deletes
    the old code's embeddings and re-ingests the new copy, so nothing case-specific is touched.
  - **Cases** - every case in this project, with a log-signal dashboard per case (exceptions,
    fatal errors, DML/SOQL counts) pulled straight from `extract_log_signals`.
  - **New Case** - just a case ID, a required debug log, and optional repro steps. Code/SDD
    already exist at the project level.
  - **Investigate** - chat with the agent, scoped to this project. Optionally pin a case from
    the dropdown; each answer shows a collapsible trace of every tool call the agent made.

Must be run from the project root (it reads/writes `project_data/` and `chroma_db/` with
relative paths, same as `ingest.py`/`agent.py`).

## Example questions

- "Investigate CASE-1001 and tell me the root cause - is this an implementation gap, a data issue, or a product bug?"
- "What does the SDD say should happen when Insurance ID is blank for CASE-1001?"
- "Show me the exact code that's throwing the exception in CASE-1001."
- "List every case in this project."

## Notes / next steps

- Natural next extensions: a batch/watch mode that auto-ingests new cases dropped into a folder;
  a markdown report output instead of terminal text; and cross-case search within a project
  ("has another case against this same project hit this same method before?") - the persistent
  per-project store already supports this, it just isn't exposed as a dedicated tool yet.
