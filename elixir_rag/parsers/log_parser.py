"""Parses a Salesforce FINEST debug log.

Two very different needs, so two different functions:

- `chunk_debug_log` produces embeddable chunks for semantic RAG search
  ("find the part of the log that talks about the insurance field").
- `extract_log_signals` does a purpose-built regex pass to pull out the
  handful of line types that actually matter for root-causing an error
  (exceptions, fatal errors, DML/SOQL activity, governor limit usage) into a
  compact structured summary.

The second one mirrors the `get_pipeline_summary` lesson from the prior
Salesforce Opportunity project: a debug log can be tens of thousands of
lines, and dumping raw lines at an LLM burns context/tokens fast and buries
the signal. An aggregation-style tool that returns "here are the 3
exceptions and the limit usage" is far more useful than "here are 40,000
lines, good luck."
"""

import re

from ..chunking import chunk_text

EXCEPTION_PATTERN = re.compile(r"^.*\|EXCEPTION_THROWN\|.*$", re.MULTILINE)
FATAL_ERROR_PATTERN = re.compile(r"^.*\|FATAL_ERROR\|.*$", re.MULTILINE)
USER_DEBUG_PATTERN = re.compile(r"^.*\|USER_DEBUG\|.*$", re.MULTILINE)
DML_BEGIN_PATTERN = re.compile(r"^.*\|DML_BEGIN\|.*$", re.MULTILINE)
SOQL_BEGIN_PATTERN = re.compile(r"^.*\|SOQL_EXECUTE_BEGIN\|.*$", re.MULTILINE)
LIMIT_USAGE_BLOCK_PATTERN = re.compile(
    r"LIMIT_USAGE_FOR_NS.*?(?=CUMULATIVE_LIMIT_USAGE_END|\Z)", re.DOTALL
)

MAX_LINES_PER_CATEGORY = 25

LOG_CHUNK_SIZE = 3000
LOG_CHUNK_OVERLAP = 300


def chunk_debug_log(text: str) -> list[str]:
    return chunk_text(text, chunk_size=LOG_CHUNK_SIZE, overlap=LOG_CHUNK_OVERLAP)


def _dedup_capped(lines: list[str], cap: int = MAX_LINES_PER_CATEGORY) -> list[str]:
    seen = set()
    out = []
    for line in lines:
        key = line.split("|", 1)[-1] if "|" in line else line
        if key in seen:
            continue
        seen.add(key)
        out.append(line.strip())
        if len(out) >= cap:
            break
    return out


def extract_log_signals(text: str) -> dict:
    exceptions = _dedup_capped(EXCEPTION_PATTERN.findall(text))
    fatal_errors = _dedup_capped(FATAL_ERROR_PATTERN.findall(text))
    user_debug = _dedup_capped(USER_DEBUG_PATTERN.findall(text))
    dml_lines = DML_BEGIN_PATTERN.findall(text)
    soql_lines = SOQL_BEGIN_PATTERN.findall(text)
    limit_blocks = LIMIT_USAGE_BLOCK_PATTERN.findall(text)

    return {
        "total_lines": text.count("\n") + 1,
        "exceptions": exceptions,
        "fatal_errors": fatal_errors,
        "dml_statement_count": len(dml_lines),
        "soql_query_count": len(soql_lines),
        "sample_user_debug": user_debug,
        "limit_usage": limit_blocks[-1].strip() if limit_blocks else None,
    }
