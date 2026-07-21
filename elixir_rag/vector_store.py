"""Persistent, project-scoped Chroma vector store.

Schema: every chunk carries a `project_id` (one project == one customer's
Elixir implementation - its SDD and SFDX code). Chunks for "sdd" and "code"
doc types are tagged with `project_id` only; chunks for "repro_steps" and
"debug_log" are additionally tagged with `case_id`, since those two are
per-support-case, not per-project.

Keeping code and the SDD strictly at the project level (never duplicated or
re-uploaded per case) is what prevents the agent from ever mixing up which
code belongs to which case, or reasoning against a stale copy of the code
from a case opened months ago - there is exactly one current copy of a
project's code, and every case under that project shares it.
"""

import chromadb

from .config import settings
from .embeddings import embed_query, embed_texts

COLLECTION_NAME = "elixir_support_cases"

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=settings.chroma_db_dir)
        _collection = _client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def project_exists(project_id: str) -> bool:
    collection = _get_collection()
    result = collection.get(where={"project_id": project_id}, limit=1)
    return len(result["ids"]) > 0


def delete_project(project_id: str) -> None:
    """Delete every chunk (sdd, code, and every case's repro/log) for a project."""
    collection = _get_collection()
    collection.delete(where={"project_id": project_id})


def delete_project_doc(project_id: str, doc_type: str) -> None:
    """Delete just one project-level doc type (sdd or code) - used to override."""
    collection = _get_collection()
    collection.delete(where={"$and": [{"project_id": project_id}, {"doc_type": doc_type}]})


def doc_type_exists(project_id: str, doc_type: str) -> bool:
    collection = _get_collection()
    result = collection.get(
        where={"$and": [{"project_id": project_id}, {"doc_type": doc_type}]}, limit=1
    )
    return len(result["ids"]) > 0


def case_exists(project_id: str, case_id: str) -> bool:
    collection = _get_collection()
    result = collection.get(
        where={"$and": [{"project_id": project_id}, {"case_id": case_id}]}, limit=1
    )
    return len(result["ids"]) > 0


def delete_case(project_id: str, case_id: str) -> None:
    """Delete a case's repro_steps/debug_log chunks. Never touches project code/SDD."""
    collection = _get_collection()
    collection.delete(where={"$and": [{"project_id": project_id}, {"case_id": case_id}]})


def upsert_chunks(
    project_id: str,
    doc_type: str,
    source_file: str,
    chunks: list[str],
    case_id: str | None = None,
) -> int:
    if not chunks:
        return 0
    collection = _get_collection()
    id_prefix = f"{project_id}::{case_id}::{doc_type}::{source_file}" if case_id \
        else f"{project_id}::{doc_type}::{source_file}"
    ids = [f"{id_prefix}::{i}" for i in range(len(chunks))]
    metadatas = []
    for i in range(len(chunks)):
        meta = {
            "project_id": project_id,
            "doc_type": doc_type,
            "source_file": source_file,
            "chunk_index": i,
        }
        if case_id:
            meta["case_id"] = case_id
        metadatas.append(meta)
    embeddings = embed_texts(chunks)
    collection.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
    return len(chunks)


def query(
    query_text: str,
    project_id: str,
    case_id: str | None = None,
    doc_type: str | None = None,
    k: int = 5,
) -> list[dict]:
    collection = _get_collection()

    conditions = [{"project_id": project_id}]
    if case_id:
        conditions.append({"case_id": case_id})
    if doc_type:
        conditions.append({"doc_type": doc_type})
    where = conditions[0] if len(conditions) == 1 else {"$and": conditions}

    result = collection.query(
        query_embeddings=[embed_query(query_text)],
        n_results=k,
        where=where,
    )

    hits = []
    for doc, meta, distance in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        hits.append({"text": doc, "metadata": meta, "distance": distance})
    return hits


def list_projects() -> list[dict]:
    """Aggregate every project's project-level doc counts (sdd, code) and case count.

    Chroma has no server-side GROUP BY, so this pulls all metadata (cheap -
    metadata only, no embeddings/documents) and aggregates client-side.
    """
    collection = _get_collection()
    result = collection.get(include=["metadatas"])

    projects: dict[str, dict] = {}
    for meta in result["metadatas"]:
        project_id = meta["project_id"]
        entry = projects.setdefault(
            project_id, {"project_id": project_id, "doc_types": {}, "case_ids": set()}
        )
        doc_type = meta["doc_type"]
        if doc_type in ("sdd", "code"):
            entry["doc_types"][doc_type] = entry["doc_types"].get(doc_type, 0) + 1
        if "case_id" in meta:
            entry["case_ids"].add(meta["case_id"])

    out = []
    for entry in projects.values():
        out.append({
            "project_id": entry["project_id"],
            "doc_types": entry["doc_types"],
            "case_count": len(entry["case_ids"]),
        })
    return sorted(out, key=lambda p: p["project_id"])


def list_cases_in_project(project_id: str) -> list[dict]:
    """Aggregate every case's repro_steps/debug_log chunk counts within one project."""
    collection = _get_collection()
    result = collection.get(where={"project_id": project_id}, include=["metadatas"])

    cases: dict[str, dict] = {}
    for meta in result["metadatas"]:
        case_id = meta.get("case_id")
        if not case_id:
            continue
        entry = cases.setdefault(case_id, {"case_id": case_id, "doc_types": {}})
        doc_type = meta["doc_type"]
        entry["doc_types"][doc_type] = entry["doc_types"].get(doc_type, 0) + 1

    return sorted(cases.values(), key=lambda c: c["case_id"])
