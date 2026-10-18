from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_name: str = "swiss-ai/Apertus-v1.5-8B"
    llm_base_url: str = "https://api.inference.cscs.ch/v1"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0
    openparldata_base_url: str = "https://api.openparldata.ch"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/parltopic.db")
    topic_config_dir: Path = Path("configs/topics")
    retrieval_top_k: int = 5
    chunk_size: int = 1400
    chunk_overlap: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()

