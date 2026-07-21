"""Tool implementations shared by the MCP server (elixir_rag/server.py) and
any other in-process caller (e.g. the web backend's agent loop).

Every tool here is project-scoped: `project_id` identifies one customer's
Elixir implementation (its code + SDD), and `case_id` (where relevant)
identifies one support case *within* that project. Code and the SDD live
only at the project level - there is exactly one current copy, never one
per case - so a caller that always passes the right `project_id` can never
have the agent mix in another customer's code or an outdated copy.

Kept as plain functions with real docstrings so `server.py` can hand them
straight to `@mcp.tool()` without re-declaring signatures or descriptions.
"""

import logging
import os
from typing import Optional

from .parsers.log_parser import extract_log_signals as _extract_log_signals
from .vector_store import list_cases_in_project as _list_cases_in_project
from .vector_store import list_projects as _list_projects
from .vector_store import query as _query

logger = logging.getLogger("elixir_rag.tools")

PROJECT_DATA_DIR = "project_data"
VALID_DOC_TYPES = {"sdd", "repro_steps", "debug_log", "code"}


def list_projects() -> list[dict]:
    """List every project (customer implementation) currently in the knowledge base.

    Returns each project's id, how many SDD/code chunks are indexed, and how
    many cases exist under it. Call this first if you don't already know the
    project_id you need.
    """
    logger.info("TOOL list_projects()")
    projects = _list_projects()
    logger.info("list_projects -> %d project(s)", len(projects))
    return projects


def list_cases(project_id: str) -> list[dict]:
    """List every support case that exists within one project.

    Returns each case's id and how many chunks are indexed per document type
    (repro_steps, debug_log). Call this if you know the project but not the
    specific case_id.

    Args:
        project_id: The project to list cases for.
    """
    logger.info("TOOL list_cases(project_id=%r)", project_id)
    cases = _list_cases_in_project(project_id)
    logger.info("list_cases -> %d case(s)", len(cases))
    return cases


def search_documents(
    query: str,
    project_id: str,
    case_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    k: int = 5,
) -> list[dict]:
    """Semantic search across a project's SDD and code, and (optionally) one case's repro steps/debug log.

    Args:
        query: Natural-language search query (e.g. "insurance id validation logic").
        project_id: The project to search within. Always required - never search across projects.
        case_id: Restrict repro_steps/debug_log results to one case within the project.
            Irrelevant for doc_type "sdd" or "code", which are project-wide.
        doc_type: Restrict to one of "sdd", "repro_steps", "debug_log", "code". Leave
            unset to search across all four.
        k: Number of chunks to return (default 5, keep small - each hit already
            includes its source file and surrounding text).
    """
    logger.info(
        "TOOL search_documents(query=%r, project_id=%r, case_id=%r, doc_type=%r, k=%r)",
        query, project_id, case_id, doc_type, k,
    )
    if doc_type and doc_type not in VALID_DOC_TYPES:
        raise ValueError(f"doc_type must be one of {sorted(VALID_DOC_TYPES)}")
    k = max(1, min(k or 5, 15))
    hits = _query(query, project_id=project_id, case_id=case_id, doc_type=doc_type, k=k)
    logger.info("search_documents -> %d hit(s)", len(hits))
    return hits


def extract_log_signals(project_id: str, case_id: str) -> dict:
    """Extract the high-signal lines from one case's raw FINEST debug log.

    Purpose-built alternative to reading the raw log: pulls out exceptions,
    fatal errors, DML/SOQL activity counts, sample USER_DEBUG lines, and the
    governor limit usage block. Always prefer this over search_documents for
    "what went wrong" / "what error was thrown" questions - the raw log can
    be tens of thousands of lines and dumping chunks of it wastes tokens and
    buries the signal.

    Args:
        project_id: The project the case belongs to.
        case_id: The case to extract signals from. Use list_cases if unknown.
    """
    logger.info("TOOL extract_log_signals(project_id=%r, case_id=%r)", project_id, case_id)
    log_path = os.path.join(PROJECT_DATA_DIR, project_id, "cases", case_id, "debug_log.log")
    if not os.path.exists(log_path):
        return {"error": f"No debug log found for case {case_id} in project {project_id}"}
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    result = _extract_log_signals(text)
    logger.info(
        "extract_log_signals -> %d exception(s), %d fatal error(s)",
        len(result["exceptions"]), len(result["fatal_errors"]),
    )
    return result


def list_code_files(project_id: str) -> list[str]:
    """List every source file path indexed for a project's SFDX code.

    Code lives at the project level (shared by every case under it), not
    per case - there is exactly one current copy.

    Args:
        project_id: The project whose code project should be listed.
    """
    logger.info("TOOL list_code_files(project_id=%r)", project_id)
    code_dir = os.path.join(PROJECT_DATA_DIR, project_id, "code")
    if not os.path.isdir(code_dir):
        return []
    files = []
    for dirpath, _dirnames, filenames in os.walk(code_dir):
        for filename in filenames:
            rel = os.path.relpath(os.path.join(dirpath, filename), code_dir)
            files.append(rel.replace("\\", "/"))
    logger.info("list_code_files -> %d file(s)", len(files))
    return sorted(files)


def get_file_content(project_id: str, file_path: str) -> dict:
    """Fetch the full, exact contents of one source file from a project's code.

    Use this once search_documents or list_code_files has told you which file
    matters - chunked search results can be partial, this returns the whole
    file so you can read the complete method/class/trigger.

    Args:
        project_id: The project the file belongs to.
        file_path: Relative path as returned by list_code_files (e.g.
            "force-app/main/default/classes/PatientIntakeTriggerHandler.cls").
    """
    logger.info("TOOL get_file_content(project_id=%r, file_path=%r)", project_id, file_path)
    code_dir = os.path.abspath(os.path.join(PROJECT_DATA_DIR, project_id, "code"))
    target = os.path.abspath(os.path.join(code_dir, file_path))
    if not target.startswith(code_dir):
        return {"error": "file_path escapes the project's code directory"}
    if not os.path.exists(target):
        return {"error": f"No such file: {file_path}"}
    with open(target, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return {"file_path": file_path, "content": content}
