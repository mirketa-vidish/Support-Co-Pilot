"""Reusable tool-calling agent loop for support-case triage (Groq, with Gemini daily-limit failover).

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

from . import llm_providers as llm
from . import tools

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
debug log(s). Never try to read the raw log via search_documents first; a log can be tens of \
thousands of lines and a purpose-built summary already exists. A case may have several debug logs \
(e.g. separate transactions or users): the combined summary tags each exception with its [log \
name] - note whether a failure appears in every log or only some, and call \
extract_log_signals(log_file=...) when you need one log's USER_DEBUG lines or governor limits.
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

MAX_TOOL_ROUNDS = 18

# Groq's free/on-demand tier caps requests at 8000 tokens per minute for this model, and the
# full conversation (system prompt + every prior tool result) is resent on every round - a
# single get_file_content on a large class or a wide search_documents hit set can blow that
# budget on its own, let alone accumulated over several rounds. Same fix as extract_log_signals
# vs. a raw debug log: chunk/cap what actually reaches the model, never send the whole thing.
MAX_TOOL_RESULT_CHARS = 3000

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
                "a case's raw FINEST debug log(s). A case may have several logs: without log_file "
                "you get a combined summary with a per-log breakdown and each exception tagged "
                "[log name]; pass log_file for one log's full detail (USER_DEBUG samples, governor "
                "limits). Always prefer this over search_documents for \"what went wrong\" questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {
                        "type": "string",
                        "description": "The case to extract signals from. Omit to use the case "
                        "already established for this conversation, if any.",
                    },
                    "log_file": {
                        "type": "string",
                        "description": "Optional. One log's name (from the combined summary's "
                        "`logs` list) to get only that log's full detail.",
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

def _create_completion(provider: "llm.Provider", messages: list[dict], is_final_round: bool):
    """One chat-completion call against `provider`. Raises one of llm.LLM_ERRORS on failure."""
    kwargs = {"model": provider.model, "messages": llm.messages_for(provider, messages)}
    # The final round sends no `tools` and a flattened, plain-text history (see
    # _flatten_for_final_answer) - both are needed, since the model will still try to call
    # a tool if it can see tool-calling turns, and Groq hard-rejects that with a 400.
    if not is_final_round:
        kwargs["tools"] = TOOL_SCHEMAS
        kwargs["tool_choice"] = "auto"
    try:
        return provider.client.chat.completions.create(**kwargs)
    except llm.LLM_ERRORS as exc:
        # Last-resort retry: if the model still emits a tool call on the tool-less final
        # round, ask once more, more bluntly, rather than discarding all gathered evidence.
        if not (is_final_round and "tool_use_failed" in str(exc)):
            raise
        kwargs["messages"] = kwargs["messages"] + [{
            "role": "user",
            "content": "Tool calls are disabled. Reply with your final written analysis only.",
        }]
        return provider.client.chat.completions.create(**kwargs)


def _all_failed_error(failures: dict[str, str], last_was_daily_limit: bool) -> str:
    """Error shown when the failing provider has no working fallback left."""
    if len(failures) == 1 and last_was_daily_limit:
        return _no_provider_error(next(iter(failures.values())).split(":")[0])
    details = " | ".join(failures.values())
    if not llm.gemini_configured():
        return f"{details}. (Add GEMINI_API_KEY to .env to fall back to Google Gemini automatically.)"
    if len(failures) == 1:
        # The other provider was never tried - say why it wasn't usable (bad key, daily limit...).
        others = [
            f"{r['label']}: {r['status']}"
            for r in llm.provider_statuses()
            if r["provider"] not in failures and not r["ready"]
        ]
        if others:
            return f"{details}. No fallback available - {'; '.join(others)}."
        return details
    return f"Both AI models failed - {details}"


def _no_provider_error(exhausted_label: str = "Groq") -> str:
    if not llm.any_configured():
        return "No AI API key is set - add GROQ_API_KEY and/or GEMINI_API_KEY to .env."
    if not llm.gemini_configured():
        return (
            f"{exhausted_label} has reached its daily limit. Add GEMINI_API_KEY to .env to fall "
            "back to Google Gemini automatically, or try again tomorrow."
        )
    return "Every configured AI model has reached its daily limit today - try again tomorrow."


def _truncate_for_model(result_text: str) -> str:
    if len(result_text) <= MAX_TOOL_RESULT_CHARS:
        return result_text
    return (
        result_text[:MAX_TOOL_RESULT_CHARS]
        + f"\n...(truncated {len(result_text) - MAX_TOOL_RESULT_CHARS} more character(s) - "
        "narrow your query, lower k, or ask for a specific portion if you need more)"
    )


# Per-result truncation alone isn't enough: the *entire* conversation (system prompt + every
# prior tool result) is resent every round, so a harder-to-investigate project that takes many
# rounds can still blow the 8000 TPM budget even with each individual result capped. Cap the
# total payload too, shrinking the OLDEST tool results first - those are the least relevant to
# whatever the model is reasoning about right now, so they're the safest to sacrifice detail on.
MAX_CONVERSATION_CHARS = 16000
TRIMMED_TOOL_RESULT_CHARS = 150


def _trim_conversation_for_budget(messages: list[dict]) -> list[dict]:
    total = sum(len(m.get("content") or "") for m in messages)
    if total <= MAX_CONVERSATION_CHARS:
        return messages

    trimmed = list(messages)
    for i, msg in enumerate(trimmed):
        if total <= MAX_CONVERSATION_CHARS:
            break
        content = msg.get("content")
        if msg.get("role") != "tool" or not content or len(content) <= TRIMMED_TOOL_RESULT_CHARS:
            continue
        total -= len(content) - TRIMMED_TOOL_RESULT_CHARS
        trimmed[i] = {
            **msg,
            "content": content[:TRIMMED_TOOL_RESULT_CHARS] + "...(older result trimmed to fit the conversation budget - re-call this tool if you need it again)",
        }
    return trimmed


FINAL_ANSWER_INSTRUCTION = (
    "You've used all available tool calls - tools are no longer available, so do NOT call any "
    "tool. Answer now in plain text using only the evidence above. If the evidence is "
    "insufficient to fully classify the root cause, say so explicitly, classify as \"Needs More "
    "Info\", and list exactly what's missing and what to check next."
)


def _flatten_for_final_answer(messages: list[dict]) -> list[dict]:
    """Rewrite the tool-calling history as plain text for the tool-less final round.

    Omitting `tools` alone isn't enough: with a long history of assistant tool_calls and
    tool-role results, the model keeps pattern-matching into yet another tool call, and Groq
    rejects that with a 400 "Tool choice is none, but model called a tool". Collapsing the
    history into one plain user message leaves no tool-calling turn structure to imitate.
    """
    head = [m for m in messages[:2] if m["role"] in ("system", "user")]
    evidence = []
    for msg in messages[2:]:
        if msg["role"] == "assistant":
            if msg.get("content"):
                evidence.append(f"Your earlier reasoning: {msg['content']}")
            for tc in msg.get("tool_calls") or []:
                fn = tc["function"]
                evidence.append(f"Called {fn['name']}({fn['arguments']})")
        elif msg["role"] == "tool":
            evidence.append(f"Result of {msg.get('name', 'tool')}:\n{msg.get('content') or ''}")
    evidence_text = "\n\n".join(evidence) if evidence else "(no evidence was gathered)"
    return head + [{
        "role": "user",
        "content": f"Evidence gathered so far:\n\n{evidence_text}\n\n{FINAL_ANSWER_INSTRUCTION}",
    }]


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

    def _extract_log_signals(case_id: Optional[str] = None, log_file: Optional[str] = None):
        resolved = case_id or pinned_case_id
        if not resolved:
            return {"error": "No case_id given and none established yet - call list_cases first."}
        return tools.extract_log_signals(project_id, resolved, log_file=log_file)

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
    preferred_provider: Optional[str] = None,
) -> dict:
    """Run the tool-calling investigation loop for one question, scoped to one project.

    Returns {"answer": str | None, "trace": [{"tool", "args", "result"}, ...],
    "rounds": int, "error": str | None, "provider"/"provider_label"/"model": who
    produced the answer, "notices": [str] (e.g. a daily-limit switch), and
    "current_model": llm.current_model_info()}. If `on_tool_call` is given, it's
    invoked as (tool_name, args, result) right after each tool call resolves,
    so a caller (e.g. a terminal REPL) can stream progress live. `preferred_provider`
    ("groq" / "gemini", from the UI's model picker) is tried first when it's ready;
    otherwise the default (Groq if usable) is used, with a notice saying why.
    """
    if not project_id:
        raise ValueError("project_id is required")

    provider, start_notice = llm.choose_provider(preferred_provider)
    notices: list[str] = [start_notice] if start_notice else []
    failures: dict[str, str] = {}  # provider name -> why it failed during this investigation

    def _result(answer, rounds, error=None):
        return {
            "answer": answer,
            "trace": trace,
            "rounds": rounds,
            "error": error,
            "provider": provider.name if provider else None,
            "provider_label": provider.label if provider else None,
            "model": provider.model if provider else None,
            "notices": notices,
            "current_model": llm.current_model_info(),
        }

    trace: list[dict] = []
    if provider is None:
        return _result(None, 0, llm.current_model_info()["note"] or _no_provider_error())

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

    for round_num in range(1, max_rounds + 1):
        # On the last round, force a direct answer instead of another tool call - otherwise a
        # case that never converges dead-ends with no synthesis at all, discarding whatever
        # evidence was already gathered (e.g. extract_log_signals may have already surfaced the
        # real exception on round 1, even if later rounds went looking for more).
        is_final_round = round_num == max_rounds
        call_messages = _trim_conversation_for_budget(messages)
        if is_final_round:
            call_messages = _flatten_for_final_answer(call_messages)

        # Any provider error (invalid key, rate limit, outage, timeout, rejected request) switches
        # to the other provider and retries this same round - the conversation so far is plain
        # OpenAI-format messages, so the other provider just continues the investigation rather
        # than starting over. A daily limit also switches every later request for the rest of the
        # day; any other error only for the rest of this investigation, so e.g. a fixed API key
        # is picked up again on the very next one.
        while True:
            try:
                response = _create_completion(provider, call_messages, is_final_round)
                break
            except llm.LLM_ERRORS as exc:
                failed = provider
                reason = llm.describe_error(exc)
                failures[failed.name] = f"{failed.label}: {reason} - {exc}"
                is_daily = llm.is_daily_limit_error(exc)
                if is_daily:
                    llm.mark_daily_limit_reached(failed)
                elif llm.is_auth_error(exc):
                    llm.record_key_problem(failed, reason)
                provider = llm.active_provider(exclude=failures.keys())
                if provider is None:
                    provider = failed  # so the result still says which model failed
                    return _result(None, round_num, _all_failed_error(failures, is_daily))
                scope = "for the rest of today" if is_daily else "for this investigation"
                notices.append(
                    f"{failed.label} failed ({reason}) - switched to {provider.label} "
                    f"({provider.model}) {scope}."
                )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return _result(msg.content, round_num)

        tool_calls = []
        for tc in msg.tool_calls:
            tc_dict = {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            # Gemini's thought signature - must be echoed back (see llm.messages_for).
            extra_content = (getattr(tc, "model_extra", None) or {}).get("extra_content")
            if extra_content:
                tc_dict["extra_content"] = extra_content
            tool_calls.append(tc_dict)
        messages.append({"role": "assistant", "content": msg.content, "tool_calls": tool_calls})

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
                "content": _truncate_for_model(result_text),
            })

    return _result(None, max_rounds, "exceeded max tool-call rounds")
