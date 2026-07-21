"""LLM-driven support triage agent for the Elixir package (EHR + RCM).

Runs the Groq tool-calling loop in `elixir_rag/agent_core.py` directly
in-process, scoped to one project (customer) at a time, letting the model
investigate a support case by retrieving from that project's Solution
Design Document, SFDX code, a case's repro steps, and FINEST debug log -
then classify the root cause.

Usage:
    python agent.py --project-id "Acme Health" "your question here"     single-shot
    python agent.py --project-id "Acme Health" --case-id CASE-1001 "..."  pin a case too
    python agent.py                                                     interactive REPL
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from elixir_rag.agent_core import investigate  # noqa: E402
from elixir_rag.tools import list_projects  # noqa: E402


def _print_tool_call(name: str, args: dict, result) -> None:
    print(f"  -> calling tool: {name}({args})")
    preview = str(result)
    if len(preview) > 300:
        preview = preview[:300] + "...(truncated)"
    print(f"  <- result: {preview}\n")


def ask(question: str, project_id: str, case_id: str | None) -> None:
    result = investigate(question, project_id=project_id, case_id=case_id, on_tool_call=_print_tool_call)
    if result["error"]:
        print(f"[stopped: {result['error']}]")
    else:
        print(result["answer"])


def _pick_project() -> str | None:
    projects = list_projects()
    if not projects:
        print("No projects in the knowledge base yet. Use ingest.py create-project first.")
        return None
    print("Projects:")
    for p in projects:
        print(f"  {p['project_id']}  ({p['case_count']} case(s))")
    project_id = input("Project ID: ").strip()
    return project_id or None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", help="Project (customer) to investigate within.")
    parser.add_argument("--case-id", help="Optional: pin a specific case within the project.")
    parser.add_argument("question", nargs="*", help="Single-shot question. Omit for interactive REPL.")
    args = parser.parse_args()

    if args.question:
        project_id = args.project_id or _pick_project()
        if not project_id:
            sys.exit(1)
        ask(" ".join(args.question), project_id, args.case_id)
        return

    print("Elixir Support triage agent. Type a question, or 'exit' to quit.\n")
    project_id = args.project_id or _pick_project()
    if not project_id:
        return
    case_id = args.case_id
    print(f"\nInvestigating project '{project_id}'"
          + (f", case '{case_id}'" if case_id else "")
          + ". Type 'switch' to change project.\n")

    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            break
        if not question or question.lower() in ("exit", "quit"):
            break
        if question.lower() == "switch":
            project_id = _pick_project()
            if not project_id:
                break
            case_id = None
            continue
        ask(question, project_id, case_id)
        print()


if __name__ == "__main__":
    main()
