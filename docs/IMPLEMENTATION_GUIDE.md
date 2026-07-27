# Implementation Guide — Support Co-pilot

This document assumes **zero prior knowledge**. If you've never written Python, never used an
API, never heard the word "embedding" — start at the top and read in order. Every later section
depends on the ones before it.

The goal is that by the end, you can point at any line of code in this project and explain what
it does and why it exists.

---

## Table of contents

1. [Concepts you need first](#1-concepts-you-need-first)
2. [What this project actually does](#2-what-this-project-actually-does)
3. [The project folder, tour](#3-the-project-folder-tour)
4. [Setting it up from zero](#4-setting-it-up-from-zero)
5. [Walking through every file](#5-walking-through-every-file)
6. [Tracing three real scenarios, step by step](#6-tracing-three-real-scenarios-step-by-step)
7. [Running it yourself](#7-running-it-yourself)
8. [Glossary](#8-glossary)

---

## 1. Concepts you need first

### 1.1 Python and virtual environments

Python is a programming language. A `.py` file is a text file full of Python instructions; you
run it with a command like `python somefile.py`, and the computer executes those instructions
top to bottom.

Python code often depends on **packages** — code other people wrote that you can reuse instead of
writing it yourself (e.g. `fastapi` for building a web server, `chromadb` for a database). These
get installed with `pip` (Python's package installer).

The problem: different projects on the same computer might need *different versions* of the same
package. A **virtual environment** (venv) is a self-contained folder holding one specific Python
installation plus its own set of packages, isolated from every other project. This project's venv
lives in `.venv/`. When you see `.venv\Scripts\python.exe` in a command, that means "run Python
*from this project's isolated environment*," not whatever Python is installed system-wide.

```powershell
python -m venv .venv                              # create the venv (done once)
.venv\Scripts\python.exe -m pip install -r requirements.txt   # install this project's packages into it
```

### 1.2 Client and server, and what an "API" is

A **server** is a program that sits and waits for requests, does something, and sends back a
response. A **client** is whatever sends the request — a web browser, a phone app, another
program. This project has a server (`webapp/main.py`, or `elixir_rag/server.py`) and clients (a
browser, or the terminal script `agent.py`).

Servers and clients usually talk over **HTTP**, the same protocol your browser uses to load a web
page. An HTTP request has:
- A **method**: `GET` (give me some data), `POST` (here's some data, do something with it), etc.
- A **path**: `/api/projects`, `/api/chat` — which "thing" on the server you want.
- Optionally, a **body**: data attached to the request (e.g. the question you're asking).

An **API** (Application Programming Interface) is just the agreed-upon set of paths and what
you're supposed to send/receive at each one. `GET /api/projects` is part of this project's API —
it means "send me the list of projects," and the server responds with that list.

### 1.3 What is JSON

**JSON** (JavaScript Object Notation) is a text format for structured data, readable by both
humans and computers. It looks like this:

```json
{
  "project_id": "Meridian Health Partners",
  "doc_types": {"sdd": 6, "code": 8},
  "case_count": 1
}
```

Keys (`"project_id"`) map to values (strings, numbers, nested objects, or lists `[...]`). Nearly
every response this project's server sends back is JSON — it's the universal "shape" for passing
structured data between a server and a client.

### 1.4 Databases, and what makes a *vector* database different

A normal database stores rows of data and lets you look them up by **exact match** — "give me the
row where `id = 42`." That's fine when you know exactly what you're looking for.

But sometimes you want to search by **meaning**, not exact words. If a debug log says "duplicate
patient record" and someone searches "same person registered twice," a normal database finds
nothing — no words match. A **vector database** solves this by storing text as **embeddings** (see
next section) — lists of numbers that capture meaning — and letting you ask "which stored pieces
of text are *closest in meaning* to this new piece of text?" This project uses **ChromaDB**, a
vector database that runs locally as a set of files on disk (in `chroma_db/`), no separate server
needed.

### 1.5 What is an "embedding"

An embedding is a list of numbers (e.g. 384 numbers) that represents a piece of text's *meaning*.
Text with similar meaning ends up with similar numbers. This project uses a small, free, local
model called `all-MiniLM-L6-v2` (via the `sentence-transformers` package) to turn any piece of
text into its embedding — this runs entirely on your own computer's CPU, no internet or API key
needed once the model is downloaded once.

Once every stored piece of text has an embedding, "search by meaning" becomes: turn the *search
query* into an embedding too, then ask the vector database for the stored embeddings mathematically
closest to it (their "distance" is small). That's the entire trick behind semantic search.

### 1.6 What is "chunking," and why not embed a whole document at once

An embedding model has a size limit — this one effectively handles roughly 256 tokens (~1,000-1,500
characters) well. A whole Solution Design Document or a 20 MB debug log is way bigger than that.
So before embedding anything, it gets split into **chunks** — smaller pieces, typically with a bit
of **overlap** between consecutive chunks (so a sentence that happens to fall right on a chunk
boundary isn't cut in a way that loses its meaning). See `elixir_rag/chunking.py` (section 5.3).

### 1.7 What is an LLM

An **LLM** (Large Language Model) is a model trained on enormous amounts of text that can read a
prompt (some input text) and generate a plausible continuation (output text) — this is what powers
ChatGPT, Claude, and, in this project, the model behind **Groq**. This project sends the LLM a
question plus some system instructions, and the LLM writes back an answer.

### 1.8 What is "tool calling" (function calling)

By itself, an LLM only knows what was in its training data — it has no way to look up *your*
specific files, *your* database, or today's date. **Tool calling** (also called "function
calling") is a mechanism where you tell the LLM: "here is a list of functions you're allowed to
ask me to run, with their names and what arguments they take" (see `TOOL_SCHEMAS` in
`elixir_rag/agent_core.py`). Instead of answering immediately, the LLM can respond with "please
call `search_documents` with `query=\"insurance id validation\"`" — your own code then actually
runs that function, and feeds the result back to the LLM as more context, so it can decide whether
it needs another tool call or is ready to answer. This back-and-forth is a **loop**: ask → maybe
call a tool → feed the result back → ask again → ... → final answer.

### 1.9 What is RAG (Retrieval-Augmented Generation)

**RAG** is the general pattern this whole project is built around: instead of asking an LLM a
question and hoping it already "knows" the answer (it doesn't — it's never seen your Salesforce
org's code or this week's debug log), you first **retrieve** the relevant pieces of your own data
(via the vector database search from section 1.4), and hand those pieces to the LLM as extra
context alongside the question, so it can **generate** an answer grounded in your actual data.
"Retrieval-Augmented Generation" = retrieval (semantic search) + augmented (added as context) +
generation (the LLM writing the answer).

### 1.10 What is MCP (Model Context Protocol)

MCP is a standardized way for an LLM-calling application to expose "tools" (see 1.8) so that *any*
MCP-compatible client (Claude Desktop, other AI apps) can discover and call them, without each
application needing custom integration code. This project's tools are exposed twice: once
generically over MCP (`elixir_rag/server.py`, for any external MCP client), and once directly
in-process for this project's own agent (`elixir_rag/agent_core.py`) — see section 5.9 for why
both exist.

### 1.11 What is FastAPI / Uvicorn / a web server

**FastAPI** is a Python package for building an HTTP API (section 1.2) with relatively little
code — you write a plain Python function, put a decorator like `@app.get("/api/projects")` above
it, and FastAPI takes care of turning it into something a browser can call, converting the
response to JSON automatically. **Uvicorn** is the actual program that runs and listens for
incoming network connections — FastAPI describes *what* to do with a request, Uvicorn is the
engine that receives it off the network and hands it to FastAPI. You start this project's server
with:

```powershell
.venv\Scripts\python.exe -m uvicorn webapp.main:app --reload
```

`webapp.main:app` means "in `webapp/main.py`, there's a variable called `app` — that's the FastAPI
application to run." `--reload` restarts the server automatically whenever you edit a file (handy
during development).

### 1.12 Environment variables and `.env` files

An **environment variable** is a named value that lives outside your code, provided by whatever
is running the program — used for things that change between machines/people or that are secret
(like API keys) and shouldn't be hard-coded into a file that might get committed to Git. A `.env`
file is a plain text file (`KEY=value` per line) that a package like `python-dotenv` reads and
loads into environment variables automatically when your program starts. This project's `.env`
holds `GROQ_API_KEY` (secret — never commit this file) and a few defaults like `GROQ_MODEL`.

---

## 2. What this project actually does

Support engineers at a company selling a Salesforce package called "Elixir" (health-record and
revenue-cycle modules) investigate customer-reported bugs. Every customer has **heavily
customized** their install on top of the base Elixir package, so most "bugs" turn out to be
issues in the *customer's own customization*, not in Elixir itself. Figuring out which is which
today means manually reading debug logs, comparing them against a design document, and reading
Apex (Salesforce's programming language) code by hand — slow, and easy to get wrong.

This project automates the first pass of that investigation: you upload a customer's design
document and code once, then for every case just the log/repro steps, and ask an LLM (via RAG +
tool calling) to investigate and classify the root cause as one of:

- **Implementation Gap** — the customer's own code doesn't correctly implement what their design
  document says it should.
- **Data Issue** — the code and design are fine; bad/missing data caused the failure.
- **Product Bug** — the failure is in unmodified Elixir base-package logic (should be rare).
- **Needs More Info** — not enough evidence yet.

### The two-tier data model — the single most important design decision

Everything else in this project follows from one split:

- **Project** (one per customer): owns the SFDX code and the design document. There is exactly
  **one current copy** of each — when a fix ships, the code is replaced in place, never
  duplicated per case.
- **Case** (many per project): just a case ID, optional repro steps, and a required debug log.
  Every case automatically shares its project's current code/design doc.

Why split it this way at all? Two reasons:
1. **Freshness.** If code were uploaded per-case, a case opened today would carry a "snapshot" of
   the code from whenever it was uploaded — if the code changed since, the agent would be
   reasoning about code that no longer matches production. Keeping one current copy at the
   project level means it's always up to date for every case, automatically.
2. **Isolation (the anti-hallucination guarantee).** Because code/design docs live at the project
   level and every tool the agent can call takes a `project_id`, and — critically — that
   `project_id` is *filled in by this project's own code before the LLM ever sees a list of
   available tools* (see section 5.8's `_build_dispatch`), the LLM has no parameter through which
   it could ask for a different customer's code. It's not "instructed" to stay in its lane — it's
   structurally unable to leave it.

---

## 3. The project folder, tour

```
elixir-support-rag/
├── .env                        Secrets/config (never committed) — GROQ_API_KEY, etc.
├── .env.example                Template showing what .env needs, with no real secrets.
├── requirements.txt            Every Python package this project needs, and minimum versions.
├── .venv/                      The isolated Python environment (see 1.1). Not committed.
├── ingest.py                   CLI + importable functions to create projects/cases.
├── agent.py                    Terminal chat REPL.
├── elixir_rag/                 The core library — everything both the CLI and web app share.
│   ├── config.py               Reads .env into a `settings` object.
│   ├── embeddings.py           Wraps the local embedding model.
│   ├── chunking.py             Generic text-splitting logic.
│   ├── vector_store.py         All ChromaDB read/write logic.
│   ├── tools.py                The 6 functions the agent (or an MCP client) can call.
│   ├── agent_core.py           The Groq tool-calling loop (the "brain" of an investigation).
│   ├── server.py               Exposes tools.py over MCP, for external MCP clients.
│   └── parsers/
│       ├── docx_parser.py      Turns a .docx design doc into chunks.
│       ├── code_parser.py      Turns an SFDX project into per-file chunks.
│       ├── text_parser.py      Turns plain text/markdown (repro steps) into chunks.
│       └── log_parser.py       Turns a debug log into chunks, plus a separate signal summary.
├── webapp/                     The browser-based UI.
│   ├── main.py                 FastAPI server: turns HTTP requests into calls into elixir_rag/.
│   └── static/                 What the browser actually loads and runs.
│       ├── index.html          Page structure (Projects list, project workspace tabs).
│       ├── app.js              All browser-side logic (fetch calls, DOM updates).
│       └── style.css           Appearance.
├── project_data/               Raw uploaded files on disk (not committed — see .gitignore).
│   └── <project_id>/code/, cases/<case_id>/debug_log.log
├── chroma_db/                  The vector database's files on disk (not committed).
├── sample_cases/CASE-1001/     A fabricated example case for testing.
├── scripts/generate_sample_sdd.py   Builds the sample .docx design doc.
└── docs/IMPLEMENTATION_GUIDE.md     This document.
```

A note on what's *not* committed to Git: `.venv/`, `chroma_db/`, `project_data/`, `.env`, and log
files (`*.log`, with an exception carved out for the sample case's log — see `.gitignore`). These
are either secrets, or things regenerated locally, or your actual customer data — none belong in
version control.

---

## 4. Setting it up from zero

Run every command from the project's root folder (`elixir-support-rag/`), in PowerShell.

**Step 1 — create the virtual environment (section 1.1) and install packages:**
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
This downloads and installs FastAPI, ChromaDB, the Groq client, sentence-transformers, python-docx,
and everything else listed in `requirements.txt`, into the isolated `.venv/` folder only.

**Step 2 — get a Groq API key (section 1.7/1.12):**
Sign up free at [console.groq.com](https://console.groq.com), create an API key, then:
```powershell
copy .env.example .env
```
Open `.env` and paste your key in as `GROQ_API_KEY=...`. This key is what lets `agent_core.py`
actually call the LLM.

**Step 3 — the first time the embedding model runs**, it downloads `all-MiniLM-L6-v2` (~90 MB)
from HuggingFace once. After that it's cached on disk and never needs the network again (see
section 5.2's offline-mode note).

**Step 4 — start the web UI:**
```powershell
.venv\Scripts\python.exe -m uvicorn webapp.main:app --reload
```
Then open `http://127.0.0.1:8000` in a browser. See section 7 for what to do once it's open.

---

## 5. Walking through every file

This section goes in the order data actually moves through the system when you ingest something,
not alphabetical order — so each file's purpose builds on the one before it.

### 5.1 `elixir_rag/config.py` — reading `.env`

```python
class Settings:
    def __init__(self):
        self.groq_api_key = _require("GROQ_API_KEY")
        self.groq_model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.chroma_db_dir = os.environ.get("CHROMA_DB_DIR", "./chroma_db")

settings = Settings()
```

`load_dotenv()` (called at the top of the file) reads `.env` and copies its `KEY=value` lines into
`os.environ` (Python's view of environment variables). `_require("GROQ_API_KEY")` reads that
variable and crashes immediately with a clear error if it's missing — better to fail loudly at
startup than get a confusing error later when something tries to call Groq with no key.
`os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")` reads a variable *with a fallback default* if
it isn't set. The last line creates one `Settings` object, `settings`, that every other file
imports and reads from — so `.env` is only ever parsed once, in one place.

### 5.2 `elixir_rag/embeddings.py` — turning text into numbers

```python
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model

def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return get_model().encode(texts, normalize_embeddings=True).tolist()

def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
```

`get_model()` loads the actual embedding model **once** and reuses it (loading it is slow — a few
seconds — so doing it once per program run instead of once per call matters). The `_model is
None` check plus `global _model` is a standard Python pattern called a **singleton**: the first
call creates it, every later call in the same running program reuses the same object.

`embed_texts` takes a list of strings and returns a list of embeddings (each one itself a list of
numbers) — `.encode(...)` does the actual math, `normalize_embeddings=True` scales each embedding
to a consistent length so that comparing "closeness" between them is a fair comparison, and
`.tolist()` converts the model's native numeric array format into plain Python lists (which is
what ChromaDB and JSON expect). `embed_query` is a convenience for the common case of embedding
just one string (a search query) instead of a batch.

The `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` lines were added after real debugging in this
project: by default, even a fully-cached model still sends small network requests to
huggingface.co on every load, just to double-check nothing changed — if that network path is
slow or blocked, every embedding call stalls. Setting these two environment variables *before*
`sentence_transformers` is even imported tells it to never attempt that check, since the model's
already downloaded once.

### 5.3 `elixir_rag/chunking.py` — splitting text into overlapping pieces

```python
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> list[str]:
    ...
```

Walking through the logic:
1. If the whole text already fits in one chunk, just return it as a single-item list — no need to
   split anything.
2. Otherwise, split on blank lines (paragraph breaks) first — `text.split("\n\n")`. If there's
   only one giant paragraph (common in a debug log with no blank lines), fall back to splitting on
   single newlines instead.
3. Walk through the paragraphs, building up a `current` chunk by appending one paragraph at a
   time. As soon as adding the next paragraph would push `current` over `chunk_size`, the chunk
   built so far is finished (appended to `chunks`) and a new one starts.
4. If a *single* paragraph is itself bigger than `chunk_size` (a dense block with no natural
   breaks), it gets hard-split at fixed character intervals instead of skipped.
5. Finally, **overlap is stitched in**: each chunk (except the first) gets the last `overlap`
   characters of the *previous* chunk prepended to it. This means if something important is
   discussed right at a chunk boundary, it still appears (partially) in both chunks, so a search
   that would otherwise miss it because it's split across two chunks has a better chance of
   finding it in at least one.

Every other parser (docx, code, text, log) calls this same function — chunking logic is written
once, here, and reused everywhere.

### 5.4 `elixir_rag/parsers/` — turning specific file types into chunks

**`docx_parser.py`** reads a Word document paragraph by paragraph. Word documents mark some
paragraphs as "Heading 1," "Heading 2," etc. (a *style*) — this parser tracks the current heading
as it walks through the document, and groups all the body text under a heading together into one
"section" before that section gets chunked. Each chunk is prefixed with `## <heading>` — so even
if a chunk is split away from its original heading text, it still says which section it came from
(e.g. a chunk from the "Known Limitations" section still starts with `## Known Limitations`,
helping the LLM understand *what part of the design doc this is* later). Tables in the document
are also pulled out separately, each row turned into a `cell | cell | cell` line.

**`code_parser.py`** walks every folder inside the uploaded SFDX project (skipping noise folders
like `.git`/`node_modules`), and for every file with a recognized Salesforce extension (`.cls`,
`.trigger`, `.xml`, etc.), reads its content, prefixes it with `File: <relative path>\n\n`, and
chunks it. Each file is chunked **on its own** — chunks from two different files are never merged
together, and the file path is baked into the very start of the text that gets embedded, since
"which file is this code even from" is the single most useful fact for the LLM to have later.

**`text_parser.py`** is the simplest one — repro steps are just plain text/markdown, so this is
"read the file, chunk it," nothing more.

**`log_parser.py`** is the most involved, because a debug log needs to serve **two very different
purposes**:
- `chunk_debug_log(text)` — chunks the log (currently 3,000 characters per chunk with 300 overlap)
  for **semantic search** (section 1.4/1.5): "find me the part of the log about the insurance
  field," even if you don't know the exact wording.
- `extract_log_signals(text)` — a completely different function using **regular expressions**
  (pattern matching over raw text) to pull out just the handful of line-types that actually matter
  for root-causing a failure: lines containing `EXCEPTION_THROWN`, `FATAL_ERROR`, counts of
  `DML_BEGIN`/`SOQL_EXECUTE_BEGIN` lines (how many database writes/queries ran), a sample of
  `USER_DEBUG` lines, and the final governor-limit-usage block. `_dedup_capped` removes duplicate
  lines and caps each category at 25 entries, so a log with the same exception repeated 500 times
  doesn't drown out everything else.

  **Why both exist**: a debug log can be tens of thousands of lines. Handing all of that to an LLM
  wastes most of its context budget on noise and can bury the one line that actually matters.
  `extract_log_signals` is a purpose-built shortcut — "skip straight to what went wrong" — that the
  agent is instructed to always try first (see `SYSTEM_PROMPT` in section 5.8), while
  `chunk_debug_log`'s output stays available for semantic search if something more specific needs
  digging up later.

### 5.5 `elixir_rag/vector_store.py` — all ChromaDB reads and writes

This file is the *only* place in the whole project that talks to ChromaDB directly — every other
file goes through the functions defined here.

```python
def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=settings.chroma_db_dir)
        _collection = _client.get_or_create_collection(COLLECTION_NAME)
    return _collection
```
Same singleton pattern as the embedding model (section 5.2) — the database connection is opened
once and reused. `PersistentClient` means Chroma stores everything as files on disk (in
`chroma_db/`), so data survives between runs. A **collection** is Chroma's word for "one named
table" — this project uses a single collection, `elixir_support_cases`, for absolutely everything
(project code, SDDs, repro steps, debug logs), distinguishing between them purely through
**metadata** tags on each chunk.

**The metadata scheme** (this *is* the two-tier data model from section 2, expressed as actual
fields on every stored chunk):
- Every chunk gets: `project_id`, `doc_type` (`"sdd"`, `"code"`, `"repro_steps"`, or
  `"debug_log"`), `source_file`, `chunk_index`.
- Only `"repro_steps"` and `"debug_log"` chunks *additionally* get a `case_id`. `"sdd"` and
  `"code"` chunks never carry a `case_id` at all — they belong to the whole project, not one case.

```python
def upsert_chunks(project_id, doc_type, source_file, chunks, case_id=None) -> int:
    ...
    embeddings = embed_texts(chunks)
    max_batch_size = _client.get_max_batch_size()
    for start in range(0, len(chunks), max_batch_size):
        end = start + max_batch_size
        collection.upsert(ids=ids[start:end], embeddings=embeddings[start:end], ...)
    return len(chunks)
```
"**Upsert**" = insert-or-update: if a chunk with that exact `id` already exists, it's replaced;
otherwise it's added fresh. Every chunk's `id` is built from `project_id::[case_id::]doc_type::
source_file::index`, so re-ingesting the exact same file naturally overwrites its old chunks
instead of creating duplicates.

The batching loop (`for start in range(0, len(chunks), max_batch_size)`) exists because of a real
bug hit while testing: Chroma refuses a single `upsert()` call carrying more chunks than its own
`max_batch_size` (observed as 5,461) — a single large debug log easily produces more chunks than
that. `range(0, len(chunks), max_batch_size)` walks through the list in fixed-size slices (`0..N`,
`N..2N`, `2N..3N`, ...), so however many chunks there are, each individual `upsert()` call stays
under the limit.

```python
def query(query_text, project_id, case_id=None, doc_type=None, k=5) -> list[dict]:
    conditions = [{"project_id": project_id}]
    if case_id: conditions.append({"case_id": case_id})
    if doc_type: conditions.append({"doc_type": doc_type})
    where = conditions[0] if len(conditions) == 1 else {"$and": conditions}
    result = collection.query(query_embeddings=[embed_query(query_text)], n_results=k, where=where)
    ...
```
This is the semantic search from section 1.4/1.5, made concrete: `embed_query(query_text)` turns
the search text into an embedding, `where=...` is Chroma's filter syntax (only compare against
chunks matching these metadata conditions — e.g. "only this project, only doc_type=sdd"),
`n_results=k` caps how many matches come back, ranked by closeness.

`list_projects()` and `list_cases_in_project()` don't do a semantic search at all — they just pull
back **every chunk's metadata** (`include=["metadatas"]` — cheap, since it skips the actual
embeddings/text) and count things up in a Python dictionary, since Chroma has no built-in "group
by project and count" query. This is fine at this project's scale; it would need rethinking if the
number of chunks grew into the millions.

### 5.6 `ingest.py` — turning uploaded files into stored chunks

This is the file that actually calls the parsers (5.4) and `vector_store.py` (5.5) in sequence.
Four public entry points:

- **`create_project(project_id, sdd_path=None, sfdx_root=None)`** — refuses to run if the project
  already exists (use the next two functions instead), creates its on-disk folder, then calls
  `set_project_sdd`/`set_project_code` if those inputs were given.
- **`set_project_code(project_id, sfdx_root, confirm_override=False)`** — if the project already
  has code indexed and `confirm_override` isn't `True`, it refuses (raises a `ValueError`) rather
  than silently overwriting; if allowed, it deletes the old code's chunks
  (`delete_project_doc(project_id, "code")`) and re-ingests the new copy. This is the "one current
  copy, replaced deliberately" rule from section 2, enforced in code, not just described in a
  comment.
- **`set_project_sdd(...)`** — the same pattern, for the design document.
- **`create_case(project_id, case_id, log_path, repro_path=None, force=False)`** — requires the
  project to already exist, refuses to overwrite an existing case unless `force=True`, chunks and
  stores the (optional) repro steps and the (required) debug log, and copies the raw log file to
  `project_data/<project_id>/cases/<case_id>/debug_log.log` (kept on disk, separately from
  Chroma, because `extract_log_signals` — section 5.4/5.7 — needs the *raw* log text, not
  embedded chunks, to run its regex pass).

At the bottom, `main()` wires these four functions up to command-line subcommands
(`create-project`, `update-project-code`, `update-project-sdd`, `create-case`) using Python's
built-in `argparse` — this is what lets you run e.g.
`python ingest.py create-case --project-id "Acme" --case-id CASE-1 --log debug.log` from a
terminal. The web app (`webapp/main.py`, section 5.11) calls the same four Python functions
directly — it doesn't shell out to this CLI, it just imports and calls the functions.

### 5.7 `elixir_rag/tools.py` — the six things the agent is allowed to do

Every function here is deliberately simple and project-scoped (`project_id` is a required
argument on every one, except where noted):

| Function | What it does |
|---|---|
| `list_projects()` | Every project + its doc counts + case count (no `project_id` — this one is global, used to *discover* which projects exist). |
| `list_cases(project_id)` | Every case inside one project, with its repro/log chunk counts. |
| `search_documents(query, project_id, case_id=None, doc_type=None, k=5)` | Semantic search, wrapping `vector_store.query()`. |
| `extract_log_signals(project_id, case_id)` | Reads the raw log file off disk and runs the regex-based summary from section 5.4. |
| `list_code_files(project_id)` | Lists every file path under `project_data/<project_id>/code/`. |
| `get_file_content(project_id, file_path)` | Reads one full file's exact content off disk — used once search/list has narrowed down *which* file matters, since a search hit is only a partial chunk. |

`get_file_content` has a security check worth calling out:
```python
code_dir = os.path.abspath(os.path.join(PROJECT_DATA_DIR, project_id, "code"))
target = os.path.abspath(os.path.join(code_dir, file_path))
if not target.startswith(code_dir):
    return {"error": "file_path escapes the project's code directory"}
```
`os.path.abspath` resolves any `..` (parent-directory) segments in the path into a real, final
path. If someone (or an LLM) passed `file_path="../../../.env"` trying to escape the project's
own code folder, the resolved `target` would land *outside* `code_dir`, and this check catches
that and refuses — a classic **path traversal** exploit, blocked.

Every function has a full **docstring** (the triple-quoted text right under `def`) — these aren't
just documentation for humans. They get passed to the LLM as the tool's *description* (see
`TOOL_SCHEMAS` in the next section), so the wording of a docstring directly shapes how well the
model understands when to use that tool.

### 5.8 `elixir_rag/agent_core.py` — the investigation loop (the most important file)

This is where the LLM actually gets asked a question and given the ability to call tools.
`investigate(question, project_id, case_id=None, ...)` is the one function everything else calls.

**Step 1 — binding `project_id` before the model ever sees a tool list:**
```python
def _build_dispatch(project_id, pinned_case_id):
    def _list_cases():
        return tools.list_cases(project_id)
    def _search_documents(query, case_id=None, doc_type=None, k=5):
        ...
        return tools.search_documents(query, project_id=project_id, case_id=effective_case_id, ...)
    ...
    return {"list_cases": _list_cases, "search_documents": _search_documents, ...}
```
`_build_dispatch` is called once per `investigate()` call, and it builds a dictionary mapping tool
*names* (strings, matching `TOOL_SCHEMAS`) to actual Python functions — but every one of those
functions is a **closure**: an inner function (`_list_cases`, `_search_documents`, ...) that
"remembers" the `project_id` value from when `_build_dispatch` was called, without that value
being one of its own parameters. Compare this to `TOOL_SCHEMAS` (further up in the file) — look
at `search_documents`'s declared parameters there: `query`, `case_id`, `doc_type`, `k`. There is no
`project_id` in that list at all. **The LLM is never even told this parameter exists** — so it's
not that the model is instructed not to change it, it's that there is no slot in the tool's
definition where it could try. This is the concrete mechanism behind the "structurally unable to
leave its lane" claim from section 2.

**Step 2 — the actual loop:**
```python
messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content}]
for round_num in range(1, max_rounds + 1):
    ...
    response = _client().chat.completions.create(model=..., messages=call_messages, tools=..., tool_choice=...)
    msg = response.choices[0].message
    if not msg.tool_calls:
        return {"answer": msg.content, ...}          # the model answered directly - done
    messages.append({"role": "assistant", "tool_calls": [...]})   # record what it asked for
    for tc in msg.tool_calls:
        result = dispatch[tc.function.name](**args)   # actually run the requested tool
        messages.append({"role": "tool", "content": ...})   # feed the result back in
    # loop again - the model sees the tool result and decides what to do next
```
`messages` is the entire conversation so far, and it grows every round: the model's own
`tool_calls` request gets appended, then each tool's real result gets appended as a `"role":
"tool"` message. On the *next* iteration of the loop, the **entire** `messages` list (system
prompt + original question + every prior tool call and result) gets sent again — the model has no
memory between calls; the whole history has to be resent every single time. This detail matters a
lot for the next few points.

**Step 3 — three defensive fixes, all added after hitting real failures while testing against
a large customer codebase:**

1. **Per-result truncation** (`_truncate_for_model`, `MAX_TOOL_RESULT_CHARS = 3000`): a single
   `get_file_content` on a large class, or a `search_documents` call returning many hits, could by
   itself be huge. Anything over 3,000 characters gets cut off with a note telling the model to
   narrow its query if it needs more — this keeps any *one* tool result from dominating the
   conversation.

2. **Whole-conversation budget** (`_trim_conversation_for_budget`, `MAX_CONVERSATION_CHARS =
   16000`): per-result truncation alone isn't enough, because — per Step 2 — the *whole*
   conversation gets resent every round, so many *individually small* tool results can still add
   up past what Groq's API allows in one request (a real error hit during testing: `"Request too
   large ... tokens per minute (TPM): Limit 8000"`). This function adds up the length of every
   message; if the total is over budget, it shrinks the **oldest** tool results first (down to 150
   characters each) — the reasoning being that older results are the least relevant to whatever
   the model is investigating *right now*, so they're the safest ones to compress. Crucially, this
   trimming only happens to the copy sent to Groq (`call_messages`) — the original, full-detail
   `messages` list is preserved, so the trace shown to the end user (in the UI) is never lossy,
   only what's re-sent to the model on later rounds is.

3. **Forced final answer** (`is_final_round`, `MAX_TOOL_ROUNDS = 18`): originally, if the model
   used up all its allowed rounds without reaching an answer, `investigate()` just gave up with
   `"error": "exceeded max tool-call rounds"` and *nothing else* — even if, say, the very first
   tool call had already surfaced the exact exception that explains the bug. Now, on the very last
   round, the tools list is **omitted from the request entirely** (`if not is_final_round:
   create_kwargs["tools"] = TOOL_SCHEMAS`) — with no tools declared, the model has nothing it
   could even attempt to call, so it's forced to answer in plain text using whatever it's already
   found. (An earlier attempt used `tool_choice="none"` instead — which still *declares* the tools
   but tells the model not to use them — but this particular model doesn't reliably honor that,
   and Groq's API hard-rejects the mismatch if the model tries anyway; omitting the tools
   parameter altogether sidesteps that by leaving no ambiguity possible.)

4. **Clean error handling** (`except GroqError as exc: return {"error": ...}`): any failure
   talking to Groq — a bad tool call the model hallucinated, a rate limit, an outage — used to
   propagate all the way up as a raw, unhandled Python exception, which FastAPI turned into a bare
   HTTP 500 with no useful information. Now it's caught and turned into a normal, readable
   response the UI already knows how to display.

**The system prompt** (`SYSTEM_PROMPT`, near the top of the file) is the actual instructions given
to the model every single call — it explains the domain (Elixir, the 90%-implementation-gap
statistic), the investigation order to follow (log signals → SDD → repro steps → code), the four
classification categories with a one-line definition each, and a rule against fabricating anything
not actually seen via a tool result. Notice this prompt is *plain English*, sent as data — changing
how the agent investigates is a matter of editing this string, not changing any Python logic.

### 5.9 `elixir_rag/server.py` — the same tools, over MCP

```python
mcp = FastMCP("elixir-support-rag")
list_projects = mcp.tool()(tools.list_projects)
list_cases = mcp.tool()(tools.list_cases)
search_documents = mcp.tool()(tools.search_documents)
...
```
`mcp.tool()` is a **decorator factory** — `mcp.tool()(tools.list_projects)` takes the real function
from `tools.py` and wraps it so the MCP framework can expose it, automatically building its schema
(name, parameters, description) straight from the function's own signature and docstring — no
separate schema to maintain by hand, unlike `TOOL_SCHEMAS` in `agent_core.py` which are written out
explicitly (because that file needs precise control over exactly which parameters the LLM is
allowed to see, per section 5.8).

The important difference from `agent_core.py`: here, `project_id` **is** an ordinary parameter an
external MCP client must supply on every call — nothing is bound in advance. This is fine for
`server.py`'s purpose (letting a general-purpose MCP client like Claude Desktop use these tools at
all), but it means the isolation guarantee from section 2 only applies to this project's *own*
agent (`agent_core.py`), not to arbitrary external MCP callers — worth remembering if this server
is ever exposed to untrusted MCP clients.

### 5.10 `agent.py` — the terminal chat program

```python
def ask(question, project_id, case_id):
    result = investigate(question, project_id=project_id, case_id=case_id, on_tool_call=_print_tool_call)
    if result["error"]:
        print(f"[stopped: {result['error']}]")
    else:
        print(result["answer"])
```
Thin wrapper around `investigate()` (section 5.8). `on_tool_call=_print_tool_call` is a **callback**
— a function passed *as a value* into `investigate()`, which calls it itself right after every
tool call resolves, so the terminal can print "`-> calling tool: ...`" live as the investigation
happens, instead of only seeing the final answer once everything is done. `main()` handles two
modes: a single question passed as a command-line argument (`python agent.py --project-id "Acme"
"what broke?"`), or an interactive loop (`while True: ... input("> ")`) that keeps asking for more
questions until you type `exit`.

### 5.11 `webapp/main.py` — the browser's server

This is the file `uvicorn webapp.main:app` runs. It's a translation layer: every function
decorated with `@app.get(...)` or `@app.post(...)` becomes one HTTP endpoint, and each one calls
straight into the same `ingest.py` / `elixir_rag/` functions already covered above — the web app
adds *no* new business logic of its own, it just adapts HTTP requests (with file uploads, form
fields, JSON bodies) into calls to functions that already exist.

Two patterns worth understanding, since they repeat across most endpoints:

**Uploaded files land as temporary folders, then get cleaned up:**
```python
tmp_dir = Path(tempfile.mkdtemp(prefix="project_create_"))
try:
    sfdx_root = _extract_code_zip(code_zip, tmp_dir)
    ...
    ingest.create_project(project_id, sdd_path=sdd_path, sfdx_root=sfdx_root)
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)
```
`tempfile.mkdtemp(...)` creates a brand-new, guaranteed-empty temporary folder (somewhere under
Windows' temp directory) for this one request. The uploaded `.zip` is saved there and unzipped,
`ingest.create_project` is called pointing at that temporary folder, and then — whether it
succeeded or raised an error — the `finally` block deletes the whole temporary folder. `ingest.py`
already copies whatever it actually needs to keep (`project_data/<id>/code/`, the debug log) onto
permanent disk itself, so nothing is lost; the temp folder was only ever scratch space for this one
upload.

**Errors become HTTP status codes:**
```python
if project_exists(project_id):
    raise HTTPException(409, f"Project '{project_id}' already exists.")
```
`HTTPException` is FastAPI's way of turning "something's wrong" into a proper HTTP response with a
status code the browser/JS can check (`409 Conflict` here — "this already exists"; `404` for "not
found"; `400` for "bad input"). `webapp/static/app.js` (next section) checks `res.ok` (true only
for 200-299 status codes) and reads `data.detail` (the message passed to `HTTPException`) to show
a useful error instead of a generic failure.

The no-cache middleware near the top,
```python
@app.middleware("http")
async def _no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response
```
runs for *every* request, before and after the actual endpoint function — it exists because
browsers otherwise cache the HTML/CSS/JS aggressively, and a real update mid-development once
appeared not to have taken effect at all (the browser was just silently showing a stale cached
copy). `no-store` tells the browser: never cache this, always re-fetch.

### 5.12 `webapp/static/` — what the browser actually runs

**`index.html`** is the page's fixed structure: a `Projects` view (list + create-project form) and
a `Project workspace` view (Overview / Cases / New Case / Investigate tabs), both present in the
HTML from the start but toggled visible/hidden with CSS classes (`.active`) rather than being
built and destroyed dynamically — simpler to reason about for a page this size.

**`app.js`** is plain JavaScript (no framework) that:
- Uses the browser's built-in `fetch()` function to call the API endpoints from section 5.11
  (e.g. `fetch("/api/projects")`), which returns a `Promise` — JavaScript's way of representing "a
  value that will exist soon, once this asynchronous operation finishes." `await fetch(...)` pauses
  that specific function until the network response actually arrives, without freezing the whole
  page.
- Builds HTML strings and inserts them into the page (`element.innerHTML = ...`) to render
  whatever came back as JSON — e.g. `renderCasesList()` turns the JSON array from `GET
  /api/projects/{id}/cases` into a grid of clickable case cards.
- Wires up event listeners (`button.addEventListener("click", ...)`) so that user actions (clicking
  a project, submitting the "New Case" form) trigger the right `fetch()` call.
- `escapeHtml()` is a small but important safety function: it converts characters like `<` and `>`
  in data that came from the server (which itself often came from an uploaded file or an LLM's
  answer) into their safe HTML-entity equivalents before insertion, so that text like `<script>` in
  a debug log can never be accidentally *executed* as real HTML/JavaScript by the browser — this is
  what prevents a class of security bug called **XSS** (cross-site scripting).

**`style.css`** defines the page's appearance using **CSS custom properties** (variables, e.g.
`--accent: #4f46e5;`, defined once under `:root` and referenced everywhere else as `var(--accent)`)
so that a `@media (prefers-color-scheme: dark)` block can redefine just those variables for dark
mode, without needing a second copy of every single style rule.

---

## 6. Tracing three real scenarios, step by step

### 6.1 Creating a project (uploading code + a design doc)

1. You fill in the "Create project" form in the browser and click submit.
2. `app.js`'s form submit handler builds a `FormData` object (the browser's representation of a
   file-upload form) and calls `fetch("/api/projects", {method: "POST", body: formData})`.
3. In `webapp/main.py`, FastAPI matches this to the `create_project` function, and — because of
   how its parameters are declared (`project_id: str = Form(...)`, `code_zip: UploadFile =
   File(...)`) — automatically parses the multipart form data into those Python variables.
4. It checks `project_exists(project_id)` (from `vector_store.py`) — if a project with that name
   is already there, it immediately returns a `409` error and stops.
5. It creates a temporary folder, saves the uploaded `.zip` into it, and unzips it.
6. It calls `ingest.create_project(project_id, sdd_path=..., sfdx_root=...)`.
7. Inside `create_project`: it makes the project's permanent folder
   (`project_data/<project_id>/`), then calls `set_project_sdd` (if an SDD was given) and
   `set_project_code`.
8. `set_project_code` calls `parse_sfdx_project(sfdx_root)` (`code_parser.py`), which walks every
   source file, reads it, prefixes it with its file path, and chunks it (`chunking.py`) — returning
   a list of `(relative_path, [chunks])` pairs.
9. For each file's chunks, `upsert_chunks(project_id, "code", rel_path, chunks)` is called
   (`vector_store.py`): it embeds every chunk (`embeddings.py` → the local model turns each chunk
   into a list of numbers) and writes them into ChromaDB, tagged with `project_id`, `doc_type=
   "code"`, `source_file=rel_path` — batched under Chroma's max-batch-size limit.
10. The unzipped code folder is also copied to `project_data/<project_id>/code/` on disk (for
    `list_code_files`/`get_file_content` to read later, section 5.7).
11. Back in `webapp/main.py`, the temporary folder is deleted, and the newly created project's
    info is fetched fresh from `list_projects()` and returned as the response's JSON.
12. `app.js` receives that JSON, hides the create-project form, and re-renders the projects list —
    now showing the new project's card.

### 6.2 Creating a case (uploading a debug log)

Same shape as above, through `webapp/main.py`'s `create_case` → `ingest.create_case(...)`, with
one extra branch: after chunking and storing the log for semantic search
(`chunk_debug_log`/`upsert_chunks` with `doc_type="debug_log"`), the *raw* log file is also copied
to `project_data/<project_id>/cases/<case_id>/debug_log.log` — kept separately on disk because
`extract_log_signals` (section 5.4/5.7) needs to re-read the actual raw text later to run its
regex pass; it doesn't (and can't) reconstruct that from the embedded chunks.

### 6.3 Asking a question — the full agent loop

Say you pick project `"Meridian Health Partners"`, case `"CASE-1001"`, and ask "Investigate this
case and tell me the root cause."

1. `app.js` sends `POST /api/chat` with `{"question": "...", "project_id": "Meridian Health
   Partners", "case_id": "CASE-1001"}` as JSON.
2. `webapp/main.py`'s `chat` function checks the project exists, then calls
   `investigate(req.question, project_id=req.project_id, case_id=req.case_id)`.
3. Inside `investigate()`: `_build_dispatch(project_id, case_id)` builds the tool functions with
   `project_id`/`case_id` already baked in (section 5.8). The conversation starts as
   `[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "Project: Meridian
   Health Partners\nCase ID: CASE-1001\n\nInvestigate this case..."}]`.
4. **Round 1**: this whole conversation, plus the list of available tools (`TOOL_SCHEMAS`), is
   sent to Groq. Per the system prompt's instructions, the model asks to call
   `extract_log_signals` first (with no arguments — `case_id` isn't even in that tool's schema
   unless the model wants to override the already-established one).
5. `dispatch["extract_log_signals"]()` runs for real: it reads
   `project_data/Meridian Health Partners/cases/CASE-1001/debug_log.log` off disk and runs the
   regex extraction (section 5.4), returning the exceptions, DML/SOQL counts, etc.
6. That result gets truncated if needed, appended to `messages` as a `"role": "tool"` message, and
   the loop goes around again — **round 2**: the model now sees the log signals (e.g. a
   `NullPointerException` in some specific class) and asks to call `search_documents(doc_type=
   "sdd", query="...")` to check what the design document says should happen.
7. `dispatch["search_documents"](...)` calls `tools.search_documents(...)` →
   `vector_store.query(...)` → embeds the query text, asks Chroma for the closest-matching `sdd`
   chunks for this `project_id`, returns them.
8. More rounds follow the same shape: `list_code_files` to find the exact class file,
   `get_file_content` to read its full source (not just a partial search chunk) once the model has
   a specific file in mind.
9. Once the model has enough evidence, it responds with **no tool call** — just a text answer,
   citing the specific exception, the SDD's relevant section, and the exact code line, ending with
   a one-line classification. `investigate()` sees `msg.tool_calls` is empty and returns
   immediately with `{"answer": ..., "trace": [...], "error": None}` — `trace` is the full list of
   every tool call made along the way, kept for display in the UI (the collapsible "N tool
   call(s)" section under each answer in the chat).
10. `webapp/main.py` returns that dictionary straight back as the response's JSON.
11. `app.js` receives it, renders the answer text as a chat bubble, and renders `trace` as a
    collapsible list of every tool call + its arguments + its result underneath.

If the model instead ran out of its 18 allowed rounds without a clean answer, step 9 wouldn't
happen naturally — instead, the *final* round is called with no tools available at all (section
5.8's forced-final-answer fix), so the model is compelled to write a best-effort text answer using
whatever it already found, rather than the whole request failing with no information at all.

---

## 7. Running it yourself

**Start the server** (from the project root):
```powershell
.venv\Scripts\python.exe -m uvicorn webapp.main:app --reload
```
Wait a few seconds for it to say `Uvicorn running on http://127.0.0.1:8000` — the first startup
loads the embedding model into memory, which takes a moment. Open that URL in a browser.

**Create your first project**: click **+ New Project**, give it a name, upload an SFDX project as
a `.zip` (must contain `package.xml` somewhere inside it), optionally upload the design document,
submit.

**Create a case inside it**: open the project, go to the **New Case** tab, give it a case ID,
upload the FINEST debug log (required), optionally the repro steps, submit.

**Investigate**: go to the **Investigate** tab, optionally pick the case from the dropdown, type a
question, hit Ask. Expand "N tool call(s)" under the answer to see exactly what evidence the agent
looked at along the way.

To do any of this from a terminal instead, see the commands documented in the main
[README.md](../README.md).

---

## 8. Glossary

| Term | Meaning |
|---|---|
| **API** | The agreed set of paths/requests a server understands, and what it sends back. |
| **Chunk / chunking** | Splitting a long document into smaller overlapping pieces small enough to embed. |
| **Client / server** | The server waits for and responds to requests; the client sends them. |
| **Closure** | A function that "remembers" a value from where it was created, without that value being one of its own parameters — how `project_id` gets bound into the agent's tools. |
| **Docstring** | The triple-quoted description under a Python function — used both as human documentation and, for tools, as what the LLM is told about that tool. |
| **Embedding** | A list of numbers representing a piece of text's meaning; similar meaning → similar numbers. |
| **Environment variable / `.env`** | A named config value supplied outside the code itself, often used for secrets. |
| **FastAPI / Uvicorn** | FastAPI describes the API; Uvicorn is the program that actually listens on the network and runs it. |
| **JSON** | The text format almost all data in this project is exchanged as. |
| **LLM** | A model that reads a prompt and generates text — here, hosted by Groq. |
| **MCP** | A standard protocol for exposing "tools" so any compatible client can call them. |
| **RAG** | Retrieval-Augmented Generation: look up your own relevant data first, then hand it to the LLM alongside the question. |
| **Singleton** | A value created once and reused everywhere after, instead of recreated every call (the embedding model, the Chroma connection). |
| **Tool calling / function calling** | The LLM asking your code to run a specific function and give it the result, instead of answering from its own training data alone. |
| **Upsert** | Insert if new, update (overwrite) if the same ID already exists. |
| **Vector database** | A database that finds stored items by meaning (embedding closeness) rather than exact match. |
| **venv (virtual environment)** | An isolated Python installation + package set, private to one project. |
