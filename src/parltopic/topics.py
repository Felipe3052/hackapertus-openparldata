from pathlib import Path

import yaml

from parltopic.models import TopicDefinition


def load_topic(path: str | Path) -> TopicDefinition:
    with Path(path).open(encoding="utf-8") as file:
        return TopicDefinition.model_validate(yaml.safe_load(file))

