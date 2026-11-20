import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self):
        # At least one of GROQ_API_KEY / GEMINI_API_KEY is needed for investigations. Groq is
        # used first; Gemini takes over whenever Groq fails (and vice-versa). Either key can
        # be left unset to run on the other provider alone. These four LLM settings are
        # re-read from .env whenever that file changes - see llm_providers.refresh_from_env_file.
        self.groq_api_key = os.environ.get("GROQ_API_KEY") or None
        self.groq_model = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY") or None
        self.gemini_model = os.environ.get("GEMINI_MODEL") or "gemini-flash-lite-latest"
        self.embedding_model = os.environ.get(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        self.chroma_db_dir = os.environ.get("CHROMA_DB_DIR", "./chroma_db")


settings = Settings()
