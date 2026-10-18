from pathlib import Path

import yaml

from parltopic.models import TopicDefinition


def load_topic(path: str | Path, title_rules: str | Path | None = None) -> TopicDefinition:
    with Path(path).open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if title_rules is not None:
        with Path(title_rules).open(encoding="utf-8") as file:
            overlay = yaml.safe_load(file)
        allowed = {"title_synonyms", "normalize_online_variants"}
        if (
            not isinstance(overlay, dict) or "title_synonyms" not in overlay
            or set(overlay) - allowed
        ):
            raise ValueError(
                "An overlay may contain only title_synonyms and normalize_online_variants"
            )
        data = {**data, **overlay}
    return TopicDefinition.model_validate(data)

