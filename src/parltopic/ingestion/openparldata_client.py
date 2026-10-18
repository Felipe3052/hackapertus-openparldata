from typing import Any

import httpx

from parltopic.config import Settings


class OpenParlDataClient:
    """Thin adapter. Endpoint-specific mapping belongs in a separate normalizer."""

    def __init__(self, settings: Settings):
        self.base_url = settings.openparldata_base_url.rstrip("/")

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = httpx.get(f"{self.base_url}/{path.lstrip('/')}", params=params, timeout=30)
        response.raise_for_status()
        return response.json()

