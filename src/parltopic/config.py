from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_name: str = "swiss-ai/Apertus-v1.5-70B"
    llm_base_url: str = "https://api.inference.cscs.ch/v1"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.5
    openparldata_base_url: str = "https://api.openparldata.ch"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/parltopic.db")
    topic_config_dir: Path = Path("configs/topics")
    retrieval_top_k: int = 5
    chunk_size: int = 1400
    chunk_overlap: int = 200
    classifier_prompt_version: str = "topic-v2"
    classifier_policy_version: str = "hybrid-v3"
    keyword_rescue_enabled: bool = True
    keyword_document_gate_enabled: bool = True
    retrieval_pin_title: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()

