from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_name: str = "swiss-ai/Apertus-v1.5-70B"
    llm_base_url: str = "https://api.inference.cscs.ch/v1"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.5
    llm_connection_reuse: bool = True
    llm_requests_per_minute: float = Field(default=30, ge=0, allow_inf_nan=False)
    # Batch 3/5 failed paired quality/coverage checks; only the research runner permits them.
    llm_batch_size: Literal[1] = 1
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
    # Shadow experiment: preserve the existing full-context path when disabled.
    aps_context_enabled: bool = False
    aps_taxonomy_path: Path = Path("configs/taxonomies/aps_topics.json")
    aps_aliases_path: Path | None = None
    aps_max_chapters: int = Field(default=4, ge=1, le=22)
    aps_max_topics: int = Field(default=8, ge=1, le=165)
    aps_context_max_segments: int = Field(default=8, ge=1, le=100)


@lru_cache
def get_settings() -> Settings:
    return Settings()

