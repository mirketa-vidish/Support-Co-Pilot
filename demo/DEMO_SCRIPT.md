# Demo script — Support Co-pilot

Everything needed is in this `demo/` folder:

| File | What it is |
|---|---|
| `Solution_Design_Document.docx` | The customer's design doc — what the code is *supposed* to do. |
| `SFDX_Code.zip` | The customer's Salesforce code (contains `package.xml`, ready to upload as-is). |
| `Repro_Steps.md` | How the issue was reproduced. |
| `Debug_Log_FINEST.log` | The raw Salesforce debug log from the failing transaction. |

**The story**: Meridian Health Partners customized the Elixir EHR module to check for duplicate
patients by Insurance ID. Walk-in patients sometimes have no Insurance ID yet — the design doc
says that case should be handled gracefully (skip the check, flag for manual review), but the
actual code never implements that check, so it throws a `NullPointerException` instead. This is a
clean **Implementation Gap** — verified working end-to-end just before this script was written.

Use a fresh name for the live demo — e.g. **`Meridian Health Partners (Demo)`** — so project
creation runs live with no "already exists" conflict.

---

## Before you're in front of your manager

1. Start the server (from the project root):
   ```powershell
   .venv\Scripts\python.exe -m uvicorn webapp.main:app --reload
   ```
   Wait for `Uvicorn running on http://127.0.0.1:8000` (~10-20s cold start), then open that URL.
2. **Rehearse the "Investigate" step once, right before the real demo.** The Groq free tier this
   project runs on has a requests-per-minute limit — most of the time it answers in under a
   minute, but if the API is under load it can take several minutes with visible "Investigating…"
   time. Running through it once beforehand confirms it's working *right now* and gives you a
   feel for the timing. If you rehearse using the demo project name, delete that project
   afterward (Overview tab doesn't have a delete button yet — simplest is picking a different demo
   project name for the real run).
3. Have this talking point ready in case the live call runs long: *"It's doing a live multi-step
   investigation — pulling the log signals, checking the design doc, then reading the actual code
   — each step is a real model call, so it's not instant."*

---

## Live walkthrough

### 1. Projects (landing screen)
Open `http://127.0.0.1:8000`. Say: *"Every customer is a project — their code and design doc live
here once, and every case they raise shares that same current copy."*

### 2. Create the project
Click **+ New Project**.
- Project / customer name: `Meridian Health Partners (Demo)`
- SFDX project code: `SFDX_Code.zip`
- Implementation document: `Solution_Design_Document.docx`

Click **Create project**. Takes about a second — say: *"That's parsed, chunked, embedded, and
indexed already."*

### 3. New Case
Go to the **New Case** tab.
- Case ID: `CASE-2001`
- FINEST debug log: `Debug_Log_FINEST.log`
- Repro steps: `Repro_Steps.md`

Click **Create case**.

### 4. Overview tab (optional, if you want to show the code browser)
Click a file under **Code files** to show the raw source is browsable directly — useful for
"trust but verify."

### 5. Investigate
Go to **Investigate**, pick `CASE-2001` from the case dropdown, ask:

> Investigate this case and tell me the root cause.

While it runs, this is a good moment for the talking point above. When it finishes, the answer
should:
- Cite the exact `NullPointerException` from the log.
- Quote the design doc's requirement to skip the duplicate check when Insurance ID is blank.
- Point at the exact line in `PatientIntakeTriggerHandler.cls` where that check is missing.
- End with a one-line classification: **Implementation Gap**.

Click **N tool call(s)** under the answer to expand the full trace — every real tool call the
agent made (`extract_log_signals`, `search_documents`, `get_file_content`, ...) with its actual
result. This is the moment to say: *"Nothing here is guessed — every claim in that answer is
backed by one of these real lookups, and it's structurally impossible for it to look at a
different customer's code, since the project is bound in before the model ever sees a tool."*

---

## If something goes wrong live

- **Investigation is slow / times out**: this is a known free-tier rate limit, not a bug — see
  `docs/IMPLEMENTATION_GUIDE.md` §5.8 if asked for detail. Fall back to narrating what the trace
  *would* show, or switch to showing the architecture diagram instead while it finishes in the
  background.
- **"Project already exists" on step 2**: you rehearsed with the same name — pick a new one
  (`Meridian Health Partners (Demo 2)`, etc.) and retry.
