"""Ingests projects and cases into the persistent knowledge base.

Two-level model:
  - A **project** (one per customer) owns the SFDX code and the Solution
    Design Document. There is exactly one current copy of each, ever - code
    is replaced in place via `update_project_code`, never re-uploaded per
    case, so the agent can never reason against a stale or wrong-customer
    copy of the code.
  - A **case** lives inside a project and only carries a case ID, optional
    repro steps, and a required FINEST debug log.

Usage:
    python ingest.py create-project --project-id "Acme Health" --sdd ./SDD.docx --code ./force-app
    python ingest.py update-project-code --project-id "Acme Health" --code ./force-app --confirm-override
    python ingest.py update-project-sdd --project-id "Acme Health" --sdd ./SDD.docx --confirm-override
    python ingest.py create-case --project-id "Acme Health" --case-id CASE-1001 --log ./debug.log --repro ./repro.md
"""

import argparse
import glob
import logging
import os
import shutil
import sys

from elixir_rag.parsers.code_parser import parse_sfdx_project
from elixir_rag.parsers.docx_parser import parse_docx
from elixir_rag.parsers.log_parser import chunk_debug_log
from elixir_rag.parsers.text_parser import parse_text
from elixir_rag.vector_store import (
    case_exists,
    delete_case,
    delete_project_doc,
    doc_type_exists,
    project_exists,
    upsert_chunks,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest")

PROJECT_DATA_DIR = "project_data"


def _find_one(folder: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        matches = sorted(glob.glob(os.path.join(folder, pattern)))
        if matches:
            return matches[0]
    return None


def _find_sfdx_root(folder: str) -> str | None:
    """Locate the SFDX project root inside an uploaded folder.

    A modern SFDX project marks its root with sfdx-project.json and keeps
    package.xml under manifest/ - treating package.xml's own folder as the
    root would index only manifest/ and silently skip all of force-app/.
    So prefer sfdx-project.json, and if only package.xml is found inside a
    manifest/ folder, step up to its parent.
    """
    package_xml_dir = None
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", ".sf", ".sfdx"}]
        if "sfdx-project.json" in filenames:
            return dirpath
        if package_xml_dir is None and "package.xml" in filenames:
            package_xml_dir = dirpath
    if package_xml_dir and os.path.basename(package_xml_dir).lower() == "manifest":
        return os.path.dirname(package_xml_dir)
    return package_xml_dir


def _project_dir(project_id: str) -> str:
    return os.path.join(PROJECT_DATA_DIR, project_id)


def _ingest_code(project_id: str, sfdx_root: str) -> int:
    file_chunks = parse_sfdx_project(sfdx_root)
    total = 0
    for rel_path, chunks in file_chunks:
        total += upsert_chunks(project_id, "code", rel_path, chunks)
    code_dir = os.path.join(_project_dir(project_id), "code")
    if os.path.exists(code_dir):
        shutil.rmtree(code_dir)
    shutil.copytree(sfdx_root, code_dir)
    logger.info("Code: %s -> %d file(s), %d chunk(s)", sfdx_root, len(file_chunks), total)
    return total


def _ingest_sdd(project_id: str, sdd_path: str) -> int:
    chunks = parse_docx(sdd_path)
    total = upsert_chunks(project_id, "sdd", os.path.basename(sdd_path), chunks)
    logger.info("SDD: %s -> %d chunk(s)", sdd_path, len(chunks))
    return total


def set_project_code(project_id: str, sfdx_root: str, confirm_override: bool = False) -> int:
    """Ingest a project's SFDX code, creating it fresh or replacing the existing copy.

    If the project already has code indexed, `confirm_override` must be True -
    this is a deliberate, explicit action since it replaces the one current
    copy every case in the project relies on.
    """
    if doc_type_exists(project_id, "code") and not confirm_override:
        raise ValueError(
            "This project already has code indexed. This would replace the existing code and "
            "its embeddings. Pass confirm_override=True to proceed."
        )
    delete_project_doc(project_id, "code")
    total = _ingest_code(project_id, sfdx_root)
    logger.info("Set code for project '%s': %d chunk(s).", project_id, total)
    return total


def set_project_sdd(project_id: str, sdd_path: str, confirm_override: bool = False) -> int:
    """Ingest a project's SDD, creating it fresh or replacing the existing copy."""
    if doc_type_exists(project_id, "sdd") and not confirm_override:
        raise ValueError(
            "This project already has an SDD indexed. This would replace it. "
            "Pass confirm_override=True to proceed."
        )
    delete_project_doc(project_id, "sdd")
    total = _ingest_sdd(project_id, sdd_path)
    logger.info("Set SDD for project '%s': %d chunk(s).", project_id, total)
    return total


def create_project(project_id: str, sdd_path: str | None = None, sfdx_root: str | None = None) -> int:
    if project_exists(project_id):
        raise ValueError(
            f"Project '{project_id}' already exists. Use set_project_code/set_project_sdd to change it."
        )
    os.makedirs(_project_dir(project_id), exist_ok=True)

    total = 0
    if sdd_path:
        total += set_project_sdd(project_id, sdd_path, confirm_override=True)
    else:
        logger.info("No SDD provided for project '%s' (optional).", project_id)

    if sfdx_root:
        total += set_project_code(project_id, sfdx_root, confirm_override=True)
    else:
        logger.warning("No SFDX project code provided for project '%s'.", project_id)

    logger.info("Created project '%s': %d total chunk(s) indexed.", project_id, total)
    return total


def create_case(
    project_id: str,
    case_id: str,
    log_path: str,
    repro_path: str | None = None,
    force: bool = False,
) -> int:
    if not project_exists(project_id):
        raise ValueError(f"No such project: '{project_id}'. Create it first.")
    if case_exists(project_id, case_id):
        if not force:
            raise ValueError(f"Case '{case_id}' already exists in project '{project_id}'. Use force to re-ingest.")
        delete_case(project_id, case_id)

    case_dir = os.path.join(_project_dir(project_id), "cases", case_id)
    os.makedirs(case_dir, exist_ok=True)

    total = 0
    if repro_path:
        chunks = parse_text(repro_path)
        total += upsert_chunks(project_id, "repro_steps", os.path.basename(repro_path), chunks, case_id=case_id)
        logger.info("Repro steps: %s -> %d chunk(s)", repro_path, len(chunks))
    else:
        logger.info("No repro steps provided for case '%s' (optional).", case_id)

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        log_text = f.read()
    chunks = chunk_debug_log(log_text)
    total += upsert_chunks(project_id, "debug_log", os.path.basename(log_path), chunks, case_id=case_id)
    shutil.copy(log_path, os.path.join(case_dir, "debug_log.log"))
    logger.info("Debug log: %s -> %d chunk(s)", log_path, len(chunks))

    logger.info("Created case '%s' in project '%s': %d total chunk(s).", case_id, project_id, total)
    return total


def _cmd_create_project(args):
    sfdx_root = args.code and (_find_sfdx_root(args.code) or args.code)
    create_project(args.project_id, sdd_path=args.sdd, sfdx_root=sfdx_root)


def _cmd_update_project_code(args):
    sfdx_root = _find_sfdx_root(args.code) or args.code
    set_project_code(args.project_id, sfdx_root, confirm_override=args.confirm_override)


def _cmd_update_project_sdd(args):
    set_project_sdd(args.project_id, args.sdd, confirm_override=args.confirm_override)


def _cmd_create_case(args):
    create_case(args.project_id, args.case_id, args.log, repro_path=args.repro, force=args.force)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_project = sub.add_parser("create-project", help="Create a new project (customer)")
    p_project.add_argument("--project-id", required=True)
    p_project.add_argument("--sdd", help="Path to the Solution Design Document (.docx). Optional.")
    p_project.add_argument("--code", help="Path to the SFDX project root or a folder containing it.")
    p_project.set_defaults(func=_cmd_create_project)

    p_code = sub.add_parser("update-project-code", help="Replace a project's SFDX code")
    p_code.add_argument("--project-id", required=True)
    p_code.add_argument("--code", required=True)
    p_code.add_argument("--confirm-override", action="store_true")
    p_code.set_defaults(func=_cmd_update_project_code)

    p_sdd = sub.add_parser("update-project-sdd", help="Replace a project's SDD")
    p_sdd.add_argument("--project-id", required=True)
    p_sdd.add_argument("--sdd", required=True)
    p_sdd.add_argument("--confirm-override", action="store_true")
    p_sdd.set_defaults(func=_cmd_update_project_sdd)

    p_case = sub.add_parser("create-case", help="Create a case inside an existing project")
    p_case.add_argument("--project-id", required=True)
    p_case.add_argument("--case-id", required=True)
    p_case.add_argument("--log", required=True, help="Path to the FINEST debug log.")
    p_case.add_argument("--repro", help="Path to repro steps (.md/.txt). Optional.")
    p_case.add_argument("--force", action="store_true")
    p_case.set_defaults(func=_cmd_create_case)

    args = parser.parse_args(sys.argv[1:])
    try:
        args.func(args)
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
