"""Reusable Groq tool-calling agent loop for support-case triage.

Calls the tool implementations in `elixir_rag/tools.py` directly (in-process)
rather than through the MCP stdio transport - this module is the shared core
used by both the terminal REPL (`agent.py`) and the web backend
(`webapp/main.py`), and an in-process function call is simpler and faster
than spawning an MCP server subprocess per request. `elixir_rag/server.py`
still exposes the same tools over MCP for external MCP clients.

Anti-hallucination design: `project_id` (and, once known, `case_id`) is bound
into the tool functions *here*, server-side, before the model ever sees a
tool schema - it is never a parameter the LLM can set. The model literally
cannot call search_documents or get_file_content against a different
project's code, because the closures in `investigate()` don't expose that
choice to it. Compare this to just instructing the model "only look at
project X" in the system prompt, which is a request the model could still
get wrong.
"""

import json
from typing import Callable, Optional

from groq import Groq

from . import tools
from .config import settings

SYSTEM_PROMPT = """You are a senior Salesforce support engineer triaging issues for the Elixir \
package (EHR and RCM modules). Every customer (project) runs a heavily customized implementation \
on top of the base package: one project owns exactly one current copy of its SFDX code and its \
Solution Design Document, shared by every case raised against it. Historically, roughly 90% of \
raised issues turn out to be implementation gaps or data issues in a customer's specific setup, \
and only 1-2% are genuine defects in the Elixir package itself. Your job is to find the real root \
cause fast and resist over-escalating to "product bug."

You are always scoped to one project - every tool call you make only ever sees that project's \
code and SDD, never another customer's. If you don't already know which case within the project \
you're investigating, call list_cases first.

Investigation process:
1. Call extract_log_signals(case_id) before anything else - it is a pre-aggregated summary of \
exceptions, fatal errors, DML/SOQL activity, and governor limit usage pulled from the raw FINEST \
debug log. Never try to read the raw log via search_documents first; the log can be tens of \
thousands of lines and a purpose-built summary already exists.
2. Use search_documents(doc_type="sdd") to find what the project's Solution Design Document says \
the intended behavior/configuration should be.
3. Use search_documents(doc_type="repro_steps") to confirm exactly how the issue was reproduced, \
if repro steps were provided for this case.
4. Once extract_log_signals points you at a specific class/trigger/method, use list_code_files \
and then get_file_content to read that file's FULL source - do not rely on a partial search chunk \
when you're about to make a root-cause claim about specific code.
5. Cross-reference all of this to classify root cause:
   - "Implementation Gap": the SDD describes a design that the actual customer-specific code does \
not correctly implement (a logic bug in customization code, not base package code).
   - "Data Issue": the code and design are correct, but the data driving the failure (a null/blank/ \
malformed field, missing record, bad configuration value) is what's actually wrong.
   - "Product Bug": the failure happens inside unmodified base Elixir package logic, with valid, \
well-formed data, and does not match a customization - this should be rare, so only conclude this \
when you've ruled out the other two with specific evidence.
   - "Needs More Info": you don't have enough evidence yet to distinguish the above.
6. Never fabricate an exception, field name, file path, or line of code you haven't actually seen \
via a tool result.

Always cite evidence (doc_type + source_file, or exact exception line) for every claim. End every \
answer with: a one-line classification (Implementation Gap / Data Issue / Product Bug / Needs More \
Info), the specific root cause, and a concrete recommended fix or next step."""

MAX_TOOL_ROUNDS = 10

# Schemas exposed to the LLM never include project_id - it is bound server-side in investigate().
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_cases",
            "description": (
                "List every support case within the current project - its id and how many "
                "repro_steps/debug_log chunks are indexed. Call this if you don't already know "
                "the case_id you need."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Semantic search across the current project's SDD and code, and (optionally) one "
                "case's repro steps/debug log."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search query."},
                    "case_id": {
                        "type": "string",
                        "description": (
                            "Restrict repro_steps/debug_log results to one case. Irrelevant for "
                            "doc_type sdd/code, which are project-wide. Omit to use the case "
                            "already established for this conversation, if any."
                        ),
                    },
                    "doc_type": {
                        "type": "string",
                        "enum": sorted(tools.VALID_DOC_TYPES),
                        "description": "Restrict to one document type. Omit to search all.",
                    },
                    "k": {"type": "integer", "description": "Number of chunks to return (default 5)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_log_signals",
            "description": (
                "Extract exceptions, fatal errors, DML/SOQL counts, and governor limit usage from "
                "one case's raw FINEST debug log. Always prefer this over search_documents for "
                "\"what went wrong\" questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {
                        "type": "string",
                        "description": "The case to extract signals from. Omit to use the case "
                        "already established for this conversation, if any.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_code_files",
            "description": "List every source file path indexed for the current project's SFDX code.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_content",
            "description": (
                "Fetch the full, exact contents of one source file from the current project's "
                "code. Use this once search_documents or list_code_files has told you which file "
                "matters - chunked search results can be partial."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path as returned by list_code_files.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
]

_groq_client: Optional[Groq] = None


def _client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.groq_api_key)
    return _groq_client


def _build_dispatch(project_id: str, pinned_case_id: Optional[str]):
    """Bind project_id (and, if known, case_id) into closures the LLM can't override."""

    def _list_cases():
        return tools.list_cases(project_id)

    def _search_documents(query: str, case_id: Optional[str] = None, doc_type: Optional[str] = None, k: int = 5):
        # sdd/code chunks carry no case_id at all (project-wide) - only default to the
        # pinned case for the two doc types that are actually per-case, otherwise a pinned
        # case_id would incorrectly zero out every sdd/code search result.
        effective_case_id = case_id
        if not effective_case_id and doc_type in ("repro_steps", "debug_log"):
            effective_case_id = pinned_case_id
        return tools.search_documents(
            query, project_id=project_id, case_id=effective_case_id, doc_type=doc_type, k=k
        )

    def _extract_log_signals(case_id: Optional[str] = None):
        resolved = case_id or pinned_case_id
        if not resolved:
            return {"error": "No case_id given and none established yet - call list_cases first."}
        return tools.extract_log_signals(project_id, resolved)

    def _list_code_files():
        return tools.list_code_files(project_id)

    def _get_file_content(file_path: str):
        return tools.get_file_content(project_id, file_path)

    return {
        "list_cases": _list_cases,
        "search_documents": _search_documents,
        "extract_log_signals": _extract_log_signals,
        "list_code_files": _list_code_files,
        "get_file_content": _get_file_content,
    }


def investigate(
    question: str,
    project_id: str,
    case_id: Optional[str] = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
    on_tool_call: Optional[Callable[[str, dict, object], None]] = None,
) -> dict:
    """Run the tool-calling investigation loop for one question, scoped to one project.

    Returns {"answer": str | None, "trace": [{"tool", "args", "result"}, ...],
    "rounds": int, "error": str | None}. If `on_tool_call` is given, it's
    invoked as (tool_name, args, result) right after each tool call resolves,
    so a caller (e.g. a terminal REPL) can stream progress live.
    """
    if not project_id:
        raise ValueError("project_id is required")

    dispatch = _build_dispatch(project_id, case_id)

    def _bound_args_for_trace(tool_name: str, args: dict) -> dict:
        # Mirrors the case_id-defaulting rule in _search_documents/_extract_log_signals,
        # so the displayed trace matches what the tool actually used - not overstating
        # a pinned case_id as applied to a project-wide sdd/code search.
        info = {"project_id": project_id}
        if not case_id:
            return info
        if tool_name == "extract_log_signals" and not args.get("case_id"):
            info["case_id"] = case_id
        elif tool_name == "search_documents" and not args.get("case_id") and args.get("doc_type") in (
            "repro_steps", "debug_log",
        ):
            info["case_id"] = case_id
        return info

    user_content = f"Project: {project_id}"
    if case_id:
        user_content += f"\nCase ID: {case_id}"
    user_content += f"\n\n{question}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    trace: list[dict] = []

    for round_num in range(1, max_rounds + 1):
        response = _client().chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return {"answer": msg.content, "trace": trace, "rounds": round_num, "error": None}

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            func = dispatch.get(tc.function.name)
            try:
                result = func(**args) if func else {"error": f"Unknown tool: {tc.function.name}"}
            except Exception as exc:
                result = {"error": str(exc)}

            if on_tool_call:
                on_tool_call(tc.function.name, args, result)
            trace.append({
                "tool": tc.function.name,
                "args": {**_bound_args_for_trace(tc.function.name, args), **args},
                "result": result,
            })

            result_text = result if isinstance(result, str) else json.dumps(result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": result_text,
            })

    return {
        "answer": None,
        "trace": trace,
        "rounds": max_rounds,
        "error": "exceeded max tool-call rounds",
    }
