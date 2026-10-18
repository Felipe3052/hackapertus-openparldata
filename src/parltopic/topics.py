from pathlib import Path

import yaml

from parltopic.models import TopicDefinition


def load_topic(path: str | Path, title_rules: str | Path | None = None) -> TopicDefinition:
    with Path(path).open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if title_rules is not None:
        with Path(title_rules).open(encoding="utf-8") as file:
            overlay = yaml.safe_load(file)
        if not isinstance(overlay, dict) or set(overlay) != {"title_synonyms"}:
            raise ValueError("A title-rule overlay must contain only title_synonyms")
        data = {**data, **overlay}
    return TopicDefinition.model_validate(data)

