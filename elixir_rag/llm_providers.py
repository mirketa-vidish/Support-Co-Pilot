"""LLM provider selection with automatic daily-limit failover (Groq <-> Google Gemini).

Groq is the primary provider. When a provider returns a *daily* rate-limit error
(Groq: "tokens/requests per day"; Gemini: a "...PerDay..." quota), it's marked
exhausted for the rest of the calendar day (local time) and every request -
including the rest of an investigation already in progress - moves to the other
provider. If that one also hits its daily limit, it switches back (if the first
is no longer exhausted). The exhausted list resets automatically the next day.

Per-minute limits deliberately do NOT trigger a switch - those clear within a
minute, and flipping providers for them would mean bouncing between models
mid-investigation for no lasting reason.

State lives in a small JSON file so the switch survives a server restart (and is
shared by the web app and the terminal REPL) for the rest of that day.

Gemini is called through Google's OpenAI-compatible endpoint, so the exact same
tool schemas and message format work for both providers.
"""

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from groq import Groq, GroqError
from openai import OpenAI, OpenAIError

from .config import Settings, settings

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Preference order - the first configured, non-exhausted provider is used.
PROVIDER_ORDER = ["groq", "gemini"]
PROVIDER_LABELS = {"groq": "Groq", "gemini": "Google Gemini"}

# Every error either SDK can raise - callers catch this tuple.
LLM_ERRORS = (GroqError, OpenAIError)

REQUEST_TIMEOUT_SECONDS = 120

# See messages_for(): Google's documented placeholder for tool calls Gemini didn't make itself.
FOREIGN_THOUGHT_SIGNATURE = {"google": {"thought_signature": "skip_thought_signature_validator"}}

STATE_FILE = Path(os.environ.get("LLM_STATE_FILE", "llm_provider_state.json"))

_state_lock = threading.Lock()
_clients: dict[str, object] = {}


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    model: str

    @property
    def client(self):
        if self.name not in _clients:
            # Both SDKs default to a 10-minute timeout - a stalled request would leave the UI
            # spinning that long. A timeout is raised as an ordinary API error instead.
            if self.name == "groq":
                _clients[self.name] = Groq(
                    api_key=settings.groq_api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=1
                )
            else:
                _clients[self.name] = OpenAI(
                    api_key=settings.gemini_api_key, base_url=GEMINI_BASE_URL,
                    timeout=REQUEST_TIMEOUT_SECONDS, max_retries=1,
                )
        return _clients[self.name]

    def as_dict(self) -> dict:
        return {"provider": self.name, "label": self.label, "model": self.model}


# ---------- Live .env reload ----------
# The server otherwise reads .env only once at startup, so commenting out / changing an API key
# silently had no effect until a restart - the UI kept (accurately) reporting the provider that
# the stale in-memory key still reached. Re-read the LLM settings whenever .env changes instead.

ENV_FILE = Path(".env")
_LLM_ENV_VARS = ("GROQ_API_KEY", "GROQ_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL")
_env_lock = threading.Lock()
_env_mtime: Optional[float] = None


def _llm_values_from_env_file() -> dict[str, Optional[str]]:
    """{var: value or None} for every LLM variable .env mentions - set OR commented out.

    .env is the source of truth for these: load_dotenv() never overrides an existing OS
    environment variable, so a GROQ_API_KEY also set in Windows' user environment would
    otherwise keep Groq active no matter what .env said. A variable .env doesn't mention at
    all is omitted, leaving any OS-level value in effect. A value starting with "#" (e.g.
    `GROQ_API_KEY= #gsk_...`) is treated as commented out - no real key starts with "#".
    """
    text = ENV_FILE.read_text(encoding="utf-8", errors="ignore")
    values = dotenv_values(ENV_FILE)
    result = {}
    for var in _LLM_ENV_VARS:
        if not re.search(rf"^\s*#?\s*(export\s+)?{var}\s*=", text, flags=re.M):
            continue
        value = (values.get(var) or "").strip()
        result[var] = None if not value or value.startswith("#") else value
    return result


def refresh_from_env_file(force: bool = False) -> None:
    """Apply .env edits to the LLM settings without a server restart (re-read only on change)."""
    global _env_mtime
    try:
        mtime = ENV_FILE.stat().st_mtime
    except OSError:
        return
    if mtime == _env_mtime and not force:
        return
    with _env_lock:
        if mtime == _env_mtime and not force:
            return
        for var, value in _llm_values_from_env_file().items():
            if value:
                os.environ[var] = value
            else:
                os.environ.pop(var, None)
        fresh = Settings()
        for attr in ("groq_api_key", "groq_model", "gemini_api_key", "gemini_model"):
            setattr(settings, attr, getattr(fresh, attr))
        _clients.clear()  # rebuild clients with the new keys on next use
        _env_mtime = mtime


def _configured_providers() -> list[Provider]:
    refresh_from_env_file()
    providers = []
    if settings.groq_api_key:
        providers.append(Provider("groq", PROVIDER_LABELS["groq"], settings.groq_model))
    if settings.gemini_api_key:
        providers.append(Provider("gemini", PROVIDER_LABELS["gemini"], settings.gemini_model))
    return sorted(providers, key=lambda p: PROVIDER_ORDER.index(p.name))


def gemini_configured() -> bool:
    refresh_from_env_file()
    return bool(settings.gemini_api_key)


def any_configured() -> bool:
    return bool(_configured_providers())


# Apply .env's precedence once at import too - before this, startup's load_dotenv() had left
# any OS-level key in place even where .env comments it out.
refresh_from_env_file(force=True)


# ---------- Daily-limit state ----------

def _load_state() -> dict:
    today = date.today().isoformat()
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if state.get("date") != today:
        # New day: every provider's daily quota has reset.
        return {"date": today, "exhausted": {}}
    state.setdefault("exhausted", {})
    return state


def _exhausted_today() -> dict:
    with _state_lock:
        return _load_state()["exhausted"]


def mark_daily_limit_reached(provider: Provider) -> None:
    with _state_lock:
        state = _load_state()
        state["exhausted"][provider.name] = datetime.now().strftime("%H:%M")
        try:
            STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass  # Still switches for this process; just won't survive a restart.


def is_daily_limit_error(exc: Exception) -> bool:
    """True only for a *daily* quota error, not a per-minute one.

    Groq:   429 "Rate limit reached ... on tokens per day (TPD)" / "requests per day (RPD)"
    Gemini: 429 RESOURCE_EXHAUSTED with a quota id like "GenerateRequestsPerDayPerProjectPerModel"
    """
    if getattr(exc, "status_code", None) != 429:
        return False
    text = _error_text(exc).lower()
    for ch in " _-":
        text = text.replace(ch, "")
    return "perday" in text


def _error_text(exc: Exception) -> str:
    """Exception message plus response body - Gemini's OpenAI-compatible endpoint returns its
    error as a JSON *list*, which the SDK leaves out of str(exc) (e.g. just "Error code: 400")."""
    return f"{exc} {getattr(exc, 'body', '') or ''}"


def is_auth_error(exc: Exception) -> bool:
    """Rejected API key. Groq answers 401; Gemini answers 400 "Invalid Auth key." /
    "API key not valid" (API_KEY_INVALID) rather than 401/403."""
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    if status in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        return True
    return status == 400 and bool(
        re.search(r"auth key|api key not valid|api_key_invalid|invalid api key", _error_text(exc), re.I)
    )


def describe_error(exc: Exception) -> str:
    """Short, human-readable reason for a provider failure (shown in the switch notice)."""
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    if is_auth_error(exc):
        return "invalid or unauthorized API key"
    if status == 429:
        return "daily limit reached" if is_daily_limit_error(exc) else "rate limit reached"
    if "Timeout" in name:
        return "request timed out"
    if "Connection" in name:
        return "could not connect"
    if status and status >= 500:
        return f"service unavailable (HTTP {status})"
    if status:
        return f"request rejected (HTTP {status})"
    return name


# ---------- API key health check ----------
# Listing a provider's models is free (no tokens) and fails fast with 401 on a bad key, so it
# tells the model picker which providers are actually usable before anyone clicks Ask. Cached
# per (provider, key value): editing a key in .env produces a new cache entry -> re-checked.

KEY_CHECK_TTL_OK = 600     # a good key is re-verified every 10 minutes
KEY_CHECK_TTL_FAIL = 60    # a failing one is retried after a minute (it may be fixed, or a blip)
_key_checks: dict[tuple[str, str], tuple[float, Optional[str]]] = {}
_key_check_lock = threading.Lock()


def _key_for(name: str) -> Optional[str]:
    return settings.groq_api_key if name == "groq" else settings.gemini_api_key


def _cached_key_problem(provider: Provider) -> tuple[bool, Optional[str]]:
    """(is_fresh, problem) from the cache, without any network call."""
    hit = _key_checks.get((provider.name, _key_for(provider.name) or ""))
    if not hit:
        return False, None
    checked_at, problem = hit
    ttl = KEY_CHECK_TTL_OK if problem is None else KEY_CHECK_TTL_FAIL
    return time.time() - checked_at < ttl, problem


def key_problem(provider: Provider) -> Optional[str]:
    """None if the provider's API key works, else a short reason (e.g. "invalid ... API key")."""
    fresh, problem = _cached_key_problem(provider)
    if fresh:
        return problem
    with _key_check_lock:
        fresh, problem = _cached_key_problem(provider)
        if fresh:
            return problem
        key = _key_for(provider.name) or ""
        try:
            if provider.name == "groq":
                client = Groq(api_key=key, timeout=10, max_retries=1)
            else:
                client = OpenAI(api_key=key, base_url=GEMINI_BASE_URL, timeout=10, max_retries=1)
            client.models.list()
            problem = None
        except LLM_ERRORS as exc:
            # Only a rejected key makes a provider unselectable. A network blip, timeout or
            # 429 says nothing about the key - and a real outage is still handled by the
            # mid-investigation failover - so don't flip the default over a transient error.
            problem = describe_error(exc) if is_auth_error(exc) else None
        _key_checks[(provider.name, key)] = (time.time(), problem)
        return problem


def record_key_problem(provider: Provider, problem: str) -> None:
    """An investigation just got an auth error from this provider - reflect it in the picker."""
    _key_checks[(provider.name, _key_for(provider.name) or "")] = (time.time(), problem)


# ---------- Selection ----------

def active_provider(exclude: frozenset[str] | set[str] = frozenset()) -> Optional[Provider]:
    """The provider to use right now, or None if none is left.

    Skips providers exhausted today, any in `exclude` (ones that already failed during the
    current investigation, e.g. an outage), and any whose key recently failed its health check.
    """
    exhausted = _exhausted_today()
    for provider in _configured_providers():
        if provider.name in exhausted or provider.name in exclude:
            continue
        fresh, problem = _cached_key_problem(provider)
        if fresh and problem:
            continue
        return provider
    return None


def provider_statuses() -> list[dict]:
    """Every known provider with whether it's ready to use now - one row per picker option."""
    configured = {p.name: p for p in _configured_providers()}
    exhausted = _exhausted_today()
    rows = []
    for name in PROVIDER_ORDER:
        model = settings.groq_model if name == "groq" else settings.gemini_model
        row = {"provider": name, "label": PROVIDER_LABELS[name], "model": model}
        if name not in configured:
            row.update(ready=False, status=f"{name.upper()}_API_KEY not set in .env")
        elif name in exhausted:
            row.update(ready=False, status=f"daily limit reached at {exhausted[name]} - available tomorrow")
        else:
            problem = key_problem(configured[name])
            row.update(ready=problem is None, status=problem or "ready")
        rows.append(row)
    return rows


def choose_provider(preferred: Optional[str] = None) -> tuple[Optional[Provider], Optional[str]]:
    """Provider to start an investigation on, plus a notice if `preferred` couldn't be used."""
    rows = provider_statuses()
    configured = {p.name: p for p in _configured_providers()}
    ready = [r["provider"] for r in rows if r["ready"]]
    if preferred in ready:
        return configured[preferred], None
    chosen = configured[ready[0]] if ready else active_provider()  # no health-checked option: try anyway
    notice = None
    if preferred and chosen and preferred != chosen.name:
        why = next((r["status"] for r in rows if r["provider"] == preferred), "unavailable")
        notice = f"{PROVIDER_LABELS.get(preferred, preferred)} is unavailable ({why}) - used {chosen.label} instead."
    return chosen, notice


def current_model_info() -> dict:
    """What the UI's model picker shows: every provider's status, and the default selection."""
    rows = provider_statuses()
    default = next((r for r in rows if r["ready"]), None)
    info = {
        "providers": rows,
        "default": default["provider"] if default else None,
        # Back-compat / convenience: the default provider's details.
        "provider": default["provider"] if default else None,
        "label": default["label"] if default else None,
        "model": default["model"] if default else None,
        "gemini_configured": gemini_configured(),
    }
    unavailable = [r for r in rows if not r["ready"]]
    if not default:
        reasons = "; ".join(f"{r['label']}: {r['status']}" for r in rows)
        info["note"] = f"No AI model is ready - {reasons}."
    elif unavailable:
        info["note"] = "; ".join(f"{r['label']} unavailable: {r['status']}" for r in unavailable) + "."
    else:
        info["note"] = None
    return info


def messages_for(provider: Provider, messages: list[dict]) -> list[dict]:
    """Adapt the shared message history to one provider's wire format.

    Newer Gemini models attach a thought signature to each tool call (`extra_content`) that
    must be echoed back on the next turn - and reject (400) any earlier tool call that lacks
    one, which is every tool call Groq made before a mid-investigation switch. Google's
    documented placeholder for history produced by another model fills those in. Groq
    rejects unknown fields, so strip the signatures in the other direction.
    """
    if provider.name == "gemini":
        adapted = []
        for msg in messages:
            if msg.get("tool_calls") and any("extra_content" not in tc for tc in msg["tool_calls"]):
                msg = {
                    **msg,
                    "tool_calls": [
                        tc if "extra_content" in tc else {**tc, "extra_content": FOREIGN_THOUGHT_SIGNATURE}
                        for tc in msg["tool_calls"]
                    ],
                }
            adapted.append(msg)
        return adapted
    adapted = []
    for msg in messages:
        if msg.get("tool_calls") and any("extra_content" in tc for tc in msg["tool_calls"]):
            msg = {
                **msg,
                "tool_calls": [{k: v for k, v in tc.items() if k != "extra_content"} for tc in msg["tool_calls"]],
            }
        adapted.append(msg)
    return adapted
