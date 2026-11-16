"""Where a case's raw debug logs live on disk.

A case can carry several FINEST debug logs (e.g. one per transaction, or the
same failure captured by different users). Each is kept under
`project_data/<project_id>/cases/<case_id>/logs/` with its original filename,
so tools and the UI can tell the agent *which* log a signal came from.

Cases created before multi-log support stored exactly one log at
`cases/<case_id>/debug_log.log`; that file is still picked up so those cases
keep working without re-ingesting.
"""

import os
import re

PROJECT_DATA_DIR = "project_data"
LEGACY_LOG_NAME = "debug_log.log"

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")


def is_log_file(filename: str) -> bool:
    """Debug logs must be uploaded as .log files (case-insensitive)."""
    return bool(filename) and filename.strip().lower().endswith(".log")


def case_dir(project_id: str, case_id: str) -> str:
    return os.path.join(PROJECT_DATA_DIR, project_id, "cases", case_id)


def logs_dir(project_id: str, case_id: str) -> str:
    return os.path.join(case_dir(project_id, case_id), "logs")


def safe_log_name(filename: str, taken: set[str]) -> str:
    """Turn an uploaded filename into a safe, unique name within one case.

    Strips any directory part and odd characters, and suffixes a counter when
    two uploads share a name (e.g. two "apex.log" files from different users),
    so neither overwrites the other on disk or in the vector store.
    """
    base = os.path.basename(filename.replace("\\", "/")).strip()
    base = _UNSAFE_CHARS.sub("_", base).strip(" .") or "debug_log.log"
    stem, ext = os.path.splitext(base)
    candidate, n = base, 2
    while candidate.lower() in {t.lower() for t in taken}:
        candidate = f"{stem}-{n}{ext}"
        n += 1
    taken.add(candidate)
    return candidate


def list_case_logs(project_id: str, case_id: str) -> list[tuple[str, str]]:
    """Return [(log_name, path), ...] for every debug log stored for a case."""
    logs = []
    legacy = os.path.join(case_dir(project_id, case_id), LEGACY_LOG_NAME)
    if os.path.isfile(legacy):
        logs.append((LEGACY_LOG_NAME, legacy))
    folder = logs_dir(project_id, case_id)
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder), key=str.lower):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                logs.append((name, path))
    return logs
