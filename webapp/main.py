"""FastAPI backend for the Elixir Support RAG web UI.

Project-first: code and the SDD live at the project (customer) level and are
never re-uploaded per case, so the agent can never mix in another
customer's code or an outdated copy - see elixir_rag/agent_core.py for how
that's enforced at the tool-dispatch layer, not just by convention here.

    GET  /api/projects                        list every project
    POST /api/projects                        create a project (code required, SDD optional)
    GET  /api/projects/{id}                    project detail: doc counts, code file list
    POST /api/projects/{id}/code               replace project code (requires confirm_override once one exists)
    POST /api/projects/{id}/sdd                replace project SDD (requires confirm_override once one exists)
    GET  /api/projects/{id}/file?path=...      fetch one source file's contents
    GET  /api/projects/{id}/cases              list cases within a project
    POST /api/projects/{id}/cases              create a case (case_id + required log + optional repro)
    GET  /api/projects/{id}/cases/{case_id}     case dashboard: log signals
    POST /api/chat                             investigate via the Groq agent, scoped to one project

Run from the project root:
    .venv\\Scripts\\python.exe -m uvicorn webapp.main:app --reload
"""

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.datastructures import UploadFile as StarletteUploadFile  # noqa: E402

import ingest  # noqa: E402
from elixir_rag import tools  # noqa: E402
from elixir_rag.agent_core import investigate  # noqa: E402
from elixir_rag.vector_store import (  # noqa: E402
    case_exists,
    list_cases_in_project,
    list_projects,
    project_exists,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Elixir Support RAG")


@app.middleware("http")
async def _no_cache(request: Request, call_next):
    # This UI's static files change frequently during development; browsers otherwise
    # cache them aggressively and silently keep showing a stale page after an update.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


class ChatRequest(BaseModel):
    question: str
    project_id: str
    case_id: Optional[str] = None


def _save_upload(upload: UploadFile, dest: Path) -> None:
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)


def _has_file(upload: Optional[UploadFile]) -> bool:
    return isinstance(upload, StarletteUploadFile) and bool(upload.filename)


def _extract_code_zip(code_zip: UploadFile, tmp_dir: Path) -> str:
    zip_path = tmp_dir / "code.zip"
    _save_upload(code_zip, zip_path)
    code_dir = tmp_dir / "code"
    code_dir.mkdir()
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(code_dir)
    return str(ingest._find_sfdx_root(str(code_dir)) or code_dir)


# ---------- Projects ----------

@app.get("/api/projects")
def get_projects():
    return list_projects()


@app.get("/api/projects/{project_id}")
def get_project_detail(project_id: str):
    project = next((p for p in list_projects() if p["project_id"] == project_id), None)
    if not project:
        raise HTTPException(404, f"No such project: {project_id}")
    return {**project, "code_files": tools.list_code_files(project_id)}


@app.post("/api/projects")
def create_project(
    project_id: str = Form(...),
    sdd: Optional[UploadFile] = File(None),
    code_zip: UploadFile = File(...),
):
    project_id = project_id.strip()
    if not project_id:
        raise HTTPException(400, "project_id is required")
    if project_exists(project_id):
        raise HTTPException(409, f"Project '{project_id}' already exists.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="project_create_"))
    try:
        sfdx_root = _extract_code_zip(code_zip, tmp_dir)
        sdd_path = None
        if _has_file(sdd):
            sdd_path = str(tmp_dir / "sdd.docx")
            _save_upload(sdd, Path(sdd_path))

        try:
            ingest.create_project(project_id, sdd_path=sdd_path, sfdx_root=sfdx_root)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    project = next((p for p in list_projects() if p["project_id"] == project_id), None)
    if not project:
        raise HTTPException(422, "Project creation ran but produced no code chunks - check the zip contains package.xml.")
    return {"ok": True, "project": project}


@app.post("/api/projects/{project_id}/code")
def update_project_code(
    project_id: str,
    confirm_override: bool = Form(False),
    code_zip: UploadFile = File(...),
):
    if not project_exists(project_id):
        raise HTTPException(404, f"No such project: {project_id}")
    tmp_dir = Path(tempfile.mkdtemp(prefix="project_code_"))
    try:
        sfdx_root = _extract_code_zip(code_zip, tmp_dir)
        try:
            total = ingest.set_project_code(project_id, sfdx_root, confirm_override=confirm_override)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return {"ok": True, "chunks_indexed": total}


@app.post("/api/projects/{project_id}/sdd")
def update_project_sdd(
    project_id: str,
    confirm_override: bool = Form(False),
    sdd: UploadFile = File(...),
):
    if not project_exists(project_id):
        raise HTTPException(404, f"No such project: {project_id}")
    tmp_dir = Path(tempfile.mkdtemp(prefix="project_sdd_"))
    try:
        sdd_path = tmp_dir / "sdd.docx"
        _save_upload(sdd, sdd_path)
        try:
            total = ingest.set_project_sdd(project_id, str(sdd_path), confirm_override=confirm_override)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return {"ok": True, "chunks_indexed": total}


@app.get("/api/projects/{project_id}/file")
def get_project_file(project_id: str, path: str):
    result = tools.get_file_content(project_id, path)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ---------- Cases ----------

@app.get("/api/projects/{project_id}/cases")
def get_cases(project_id: str):
    if not project_exists(project_id):
        raise HTTPException(404, f"No such project: {project_id}")
    return list_cases_in_project(project_id)


@app.get("/api/projects/{project_id}/cases/{case_id}")
def get_case_detail(project_id: str, case_id: str):
    if not case_exists(project_id, case_id):
        raise HTTPException(404, f"No such case: {case_id}")
    signals = tools.extract_log_signals(project_id, case_id)
    return {
        "project_id": project_id,
        "case_id": case_id,
        "log_signals": None if "error" in signals else signals,
    }


@app.post("/api/projects/{project_id}/cases")
def create_case(
    project_id: str,
    case_id: str = Form(...),
    force: bool = Form(False),
    repro: Optional[UploadFile] = File(None),
    log: UploadFile = File(...),
):
    if not project_exists(project_id):
        raise HTTPException(404, f"No such project: {project_id}")
    case_id = case_id.strip()
    if not case_id:
        raise HTTPException(400, "case_id is required")
    if not force and case_exists(project_id, case_id):
        raise HTTPException(409, f"Case '{case_id}' already exists. Check 'force re-ingest' to overwrite.")

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"case_{case_id}_"))
    try:
        log_path = tmp_dir / "case.log"
        _save_upload(log, log_path)

        repro_path = None
        if _has_file(repro):
            ext = ".md" if repro.filename.lower().endswith(".md") else ".txt"
            repro_path = tmp_dir / f"repro{ext}"
            _save_upload(repro, repro_path)

        try:
            ingest.create_case(
                project_id, case_id, str(log_path),
                repro_path=str(repro_path) if repro_path else None,
                force=force,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    case = next((c for c in list_cases_in_project(project_id) if c["case_id"] == case_id), None)
    return {"ok": True, "case": case}


# ---------- Chat ----------

@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(400, "question is required")
    if not project_exists(req.project_id):
        raise HTTPException(404, f"No such project: {req.project_id}")
    return investigate(req.question, project_id=req.project_id, case_id=req.case_id or None)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
