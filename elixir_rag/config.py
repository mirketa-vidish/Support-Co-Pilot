import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings:
    def __init__(self):
        self.groq_api_key = _require("GROQ_API_KEY")
        self.groq_model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        self.embedding_model = os.environ.get(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        self.chroma_db_dir = os.environ.get("CHROMA_DB_DIR", "./chroma_db")


settings = Settings()
