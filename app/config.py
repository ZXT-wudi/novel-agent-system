from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    SILICONFLOW_MODEL: str = "deepseek-ai/DeepSeek-V4-Pro"
    SILICONFLOW_EMBEDDING_MODEL: str = "BAAI/bge-large-zh-v1.5"
    EMBEDDING_DIMENSION: int = 1024

    TAVILY_API_KEY: str = ""

    DATABASE_URL: str = "sqlite+aiosqlite:///./novel_writer.db"

    CHROMA_PERSIST_DIR: str = str(Path(__file__).parent.parent / "chroma_data")

    MAX_REVISION_ROUNDS: int = 3
    PREVIOUS_CHAPTERS_FULL_COUNT: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
